"""Compactor - implements selective compaction logic."""

from __future__ import annotations

import json
import re
from typing import Any

from compaction.memory import WorkingMemory, Attempt, Artifact
from compaction.policy import CompactionPolicy


class Compactor:
    """Implements selective compaction: keep important context, drop/summarize rest."""
    
    def __init__(self, policy: CompactionPolicy = None):
        self.policy = policy or CompactionPolicy()
    
    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars per token)."""
        return max(1, len(text) // 4)
    
    def extract_working_memory(self, messages: list[dict]) -> WorkingMemory:
        """Extract critical context from message history."""
        memory = WorkingMemory()
        
        for msg in messages:
            content = msg.get("content", "") if isinstance(msg.get("content"), str) else str(msg.get("content", ""))
            role = msg.get("role", "")
            
            # Extract goal/objective
            if not memory.goal and re.search(r'(goal|objective|task|fix|solve|implement)', content, re.I):
                # Look for first user message that states goal
                if role == "user" and len(content) < 500:
                    memory.goal = content.strip()[:200]
            
            # Extract issue/bug
            if re.search(r'(bug|error|issue|problem|fail|broken|crash|exception|timeout)', content, re.I):
                if not memory.current_issue and role in ["user", "assistant"]:
                    # Extract first sentence mentioning issue
                    match = re.search(r'([^.]*?(bug|error|issue|problem|fail|broken|crash|exception|timeout)[^.]*\.)', content, re.I)
                    if match and len(match.group(0)) < 200:
                        memory.current_issue = match.group(0).strip()
            
            # Extract error details
            if re.search(r'(Error:|Exception:|Traceback|FAILED|failed with|status.*[45]\d\d)', content):
                if not memory.error_details:
                    # Get relevant error line
                    for line in content.split('\n'):
                        if re.search(r'(Error:|Exception:|Traceback|FAILED|timeout|[45]\d\d)', line):
                            memory.error_details = line.strip()[:300]
                            break
            
            # Extract approaches tried
            if re.search(r'(tried|attempt|approach|tested|checked|looked at)', content, re.I) and role == "assistant":
                # Try to extract approach
                sentences = re.split(r'[.!?]\s+', content)
                for s in sentences:
                    if re.search(r'(tried|attempt|approach|tested|checked)', s, re.I) and len(s) < 150:
                        # Look for result
                        result_match = re.search(r'(result|outcome|found|discovered|led to|caused).*$', s, re.I)
                        result = result_match.group(0)[:100] if result_match else ""
                        # Avoid duplicates
                        if not any(a.approach[:50] == s[:50] for a in memory.approaches_tried):
                            memory.approaches_tried.append(Attempt(approach=s.strip(), result=result.strip(), status="tried"))
                        break
            
            # Extract next steps
            if re.search(r'(next step|todo|need to|should|will|plan to|going to)', content, re.I):
                sentences = re.split(r'[.!?]\s+', content)
                for s in sentences:
                    if re.search(r'(next step|todo|need to|should do|plan)', s, re.I) and len(s) < 120:
                        step = re.sub(r'^(next step:|todo:|we need to|i need to|should)\s*', '', s, flags=re.I).strip()
                        if step and step not in memory.next_steps:
                            memory.next_steps.append(step)
            
            # Extract decisions
            if re.search(r'(decided|decision|chose|going with|will use)', content, re.I):
                sentences = re.split(r'[.!?]\s+', content)
                for s in sentences:
                    if re.search(r'(decided|decision|chose|going with)', s, re.I) and len(s) < 120:
                        if s.strip() not in memory.key_decisions:
                            memory.key_decisions.append(s.strip())
            
            # Extract facts
            if re.search(r'(found that|discovered|note that|important|key finding)', content, re.I):
                sentences = re.split(r'[.!?]\s+', content)
                for s in sentences:
                    if re.search(r'(found that|discovered|note that)', s, re.I) and len(s) < 120:
                        if s.strip() not in memory.facts:
                            memory.facts.append(s.strip())
            
            # Extract artifacts/files
            file_matches = re.findall(r'[\w\-/]+\.\w+', content)
            for f in file_matches:
                if any(ext in f for ext in ['.py', '.js', '.ts', '.java', '.json', '.log', '.txt', '.yaml', '.yml']):
                    if not any(a.path == f for a in memory.artifacts):
                        memory.artifacts.append(Artifact(path=f))
        
        # Set defaults if empty
        if not memory.goal and messages:
            for msg in messages:
                if msg.get("role") == "user":
                    content = msg.get("content", "") if isinstance(msg.get("content"), str) else str(msg.get("content", ""))
                    memory.goal = content.strip()[:200]
                    break
        
        return memory
    
    def is_redundant_ack(self, content: str) -> bool:
        """Check if message is just an acknowledgment."""
        acks = ['ok', 'okay', 'got it', 'understood', 'yes', 'no', 'thanks', 'thank you', 'done']
        content_clean = content.strip().lower()
        return content_clean in acks or len(content_clean) < 10 and content_clean in acks
    
    def truncate_logs(self, content: str) -> str:
        """Truncate large log content keeping important parts."""
        lines = content.split('\n')
        if len(lines) <= self.policy.max_log_lines_to_keep:
            return content
        
        # Keep first N/3 and last 2N/3, try to keep error lines
        keep_first = self.policy.max_log_lines_to_keep // 3
        keep_last = self.policy.max_log_lines_to_keep * 2 // 3
        error_lines = []
        for i, line in enumerate(lines):
            if re.search(r'(ERROR|FATAL|Exception|FAIL|timeout|[45]\d\d)', line, re.I):
                error_lines.append((i, line))
        
        result = []
        result.append(f"[LOG TRUNCATED - {len(lines)} lines total, kept important parts]")
        result.extend(lines[:keep_first])
        result.append(f"[... {len(lines) - keep_first - keep_last} lines omitted ...]")
        # Add error lines if not in range
        for idx, line in error_lines[-10:]:  # Keep up to 10 error lines
            if idx >= keep_first and idx < len(lines) - keep_last:
                result.append(f"[ERROR] {line}")
        result.extend(lines[-keep_last:])
        return '\n'.join(result)
    
    def compact(self, messages: list[dict], memory: WorkingMemory = None) -> tuple[list[dict], WorkingMemory, dict]:
        """
        Perform selective compaction on messages.
        Returns (compacted_messages, updated_memory, stats)
        """
        if memory is None:
            memory = self.extract_working_memory(messages)
        else:
            # Merge with extracted info
            extracted = self.extract_working_memory(messages)
            memory = self._merge_memory(memory, extracted)
        
        compacted = []
        stats = {
            "original_count": len(messages),
            "original_tokens": sum(self.estimate_tokens(str(m.get("content", ""))) for m in messages),
            "dropped": 0,
            "summarized": 0,
            "truncated": 0
        }
        
        # Keep system messages in place; history compaction operates on turns.
        for msg in messages:
            if (
                msg.get("role") == "system"
                and msg.get("type") != "system_memory"
                and self.policy.keep_system_messages
            ):
                compacted.append(msg.copy())

        history_messages = [
            msg for msg in messages
            if msg.get("role") != "system" and msg.get("type") != "system_memory"
        ]
        user_positions = [i for i, msg in enumerate(history_messages) if msg.get("role") == "user"]
        if len(user_positions) > self.policy.keep_recent_turns:
            # Start at a user boundary so a tool result is never retained without
            # the assistant tool call that produced it (or vice versa).
            start_idx = user_positions[-self.policy.keep_recent_turns]
        else:
            start_idx = 0
        recent_messages = history_messages[start_idx:]
        latest_user_index = max(
            (i for i, msg in enumerate(recent_messages) if msg.get("role") == "user"),
            default=-1,
        )

        # Process old messages - summarize/drop
        old_messages = history_messages[:start_idx]
        if old_messages and self.policy.summarize_old_turns:
            # Create summary of old turns
            summary_parts = ["[COMPACTED HISTORY]"]
            summary_parts.append(f"Previous {len(old_messages)} turns compacted. Key information preserved in Working Memory above.")
            # Add brief summary of user questions/issues
            for msg in old_messages:
                if msg.get("role") == "user":
                    content = str(msg.get("content", ""))
                    if len(content) < 100:
                        summary_parts.append(f"- User: {content}")
            summary_msg = {
                "role": "assistant",
                "content": "\n".join(summary_parts),
                "type": "thought"  # Mark as compacted summary
            }
            compacted.append(summary_msg)
            stats["summarized"] = len(old_messages)
        
        # Process recent messages
        for recent_index, msg in enumerate(recent_messages):
            content = str(msg.get("content", ""))
            
            # Drop redundant acks if policy says so
            if (
                self.policy.drop_redundant_acks
                and recent_index != latest_user_index
                and self.is_redundant_ack(content)
                and msg.get("role") == "user"
            ):
                stats["dropped"] += 1
                continue
            
            # Truncate large logs
            if self.policy.truncate_large_logs and len(content) > 2000:
                if 'log' in str(msg).lower() or re.search(r'(ERROR|INFO|DEBUG|WARN)', content):
                    new_msg = msg.copy()
                    new_msg["content"] = self.truncate_logs(content)
                    compacted.append(new_msg)
                    stats["truncated"] += 1
                    continue
            
            compacted.append(msg.copy())
        
        # Insert working memory at the beginning (after system messages)
        if self.policy.extract_working_memory and memory.goal:
            # Find position to insert (after system messages)
            insert_pos = 0
            for i, m in enumerate(compacted):
                if m.get("role") == "system":
                    insert_pos = i + 1
                else:
                    break
            memory_msg = {
                "role": "system",
                "content": memory.render(),
                "type": "system_memory"
            }
            compacted.insert(insert_pos, memory_msg)
        
        stats["compacted_count"] = len(compacted)
        stats["compacted_tokens"] = sum(self.estimate_tokens(str(m.get("content", ""))) for m in compacted)
        stats["reduction"] = round((1 - stats["compacted_tokens"] / max(1, stats["original_tokens"])) * 100, 1)
        
        return compacted, memory, stats
    
    def _merge_memory(self, existing: WorkingMemory, extracted: WorkingMemory) -> WorkingMemory:
        """Merge extracted memory into existing."""
        if extracted.goal and not existing.goal:
            existing.goal = extracted.goal
        if extracted.current_issue and not existing.current_issue:
            existing.current_issue = extracted.current_issue
        if extracted.error_details and not existing.error_details:
            existing.error_details = extracted.error_details
        
        # Merge lists avoiding duplicates
        for a in extracted.approaches_tried:
            if not any(a2.approach[:50] == a.approach[:50] for a2 in existing.approaches_tried):
                existing.approaches_tried.append(a)
        for s in extracted.next_steps:
            if s not in existing.next_steps:
                existing.next_steps.append(s)
        for d in extracted.key_decisions:
            if d not in existing.key_decisions:
                existing.key_decisions.append(d)
        for f in extracted.facts:
            if f not in existing.facts:
                existing.facts.append(f)
        for q in extracted.open_questions:
            if q not in existing.open_questions:
                existing.open_questions.append(q)
        for a in extracted.artifacts:
            if not any(a2.path == a.path for a2 in existing.artifacts):
                existing.artifacts.append(a)
        
        return existing
