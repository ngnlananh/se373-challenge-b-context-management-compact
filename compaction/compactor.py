"""Compactor - implements selective compaction logic."""

from __future__ import annotations

import json
import re
from typing import Any

from compaction.memory import WorkingMemory, Attempt, Artifact, is_actionable_step
from compaction.policy import CompactionPolicy


class Compactor:
    """Implements selective compaction: keep important context, drop/summarize rest."""
    
    def __init__(self, policy: CompactionPolicy = None):
        self.policy = policy or CompactionPolicy()
    
    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars per token)."""
        return max(1, len(text) // 4)

    @staticmethod
    def _clean_memory_line(line: str) -> str:
        """Remove common Markdown markers before parsing structured memory labels."""
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = re.sub(r"__(.*?)__", r"\1", line)
        line = line.replace("`", "")
        return line.strip()

    @staticmethod
    def _normalize_memory_text(value: str) -> str:
        """Normalize punctuation/formatting so the same note is stored once."""
        value = re.sub(r"[`*_]", "", value).casefold()
        value = re.sub(r"\s+", " ", value).strip()
        return value.strip(" .,:;!?-–—")

    def _extract_attempts_and_next_steps(self, messages: list[dict], memory: WorkingMemory) -> None:
        """Read explicitly labeled notes without mistaking free-form instructions for memory."""
        approach_label = re.compile(
            r"^(?:approach(?:es)?\s+tried|tried\s+approach|cách\s+đã\s+thử|phương\s+án\s+đã\s+thử)"
            r"(?:\s*#?\d+)?\s*:\s*(.*)$",
            re.IGNORECASE,
        )
        result_label = re.compile(r"^(?:result|outcome|kết\s+quả(?:\s+thử)?):\s*(.*)$", re.IGNORECASE)
        next_label = re.compile(
            r"^(?:next\s+steps?|bước\s+tiếp\s+theo|việc\s+tiếp\s+theo):\s*(.*)$",
            re.IGNORECASE,
        )
        section_label = re.compile(r"^(?:issue|goal|error|task|mục\s+tiêu|lỗi|vấn\s+đề):", re.IGNORECASE)
        list_item = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)(.+)$")

        def append_result(attempt: Attempt, result: str) -> None:
            result = result.strip(" \t-*•")
            if not result:
                return
            existing_parts = [part.strip() for part in attempt.result.split(" | ") if part.strip()]
            normalized = self._normalize_memory_text(result)
            normalized_parts = [self._normalize_memory_text(part) for part in existing_parts]
            if normalized in normalized_parts:
                return
            existing_parts.append(result)
            attempt.result = " | ".join(existing_parts)

        def append_step(step: str, memory: WorkingMemory) -> None:
            step = self._clean_memory_line(step).strip(" \t-*•")
            # Keep only action items; summaries/results often sit under a
            # model-generated "Next steps" heading but are not steps.
            if not is_actionable_step(step):
                return
            if not step or len(step) > 300 or len(memory.next_steps) >= 6:
                return
            normalized = self._normalize_memory_text(step)
            if not any(self._normalize_memory_text(old) == normalized for old in memory.next_steps):
                memory.next_steps.append(step)

        def add_attempt(approach: str, result: str = "") -> Attempt | None:
            approach = approach.strip(" \t-*•")
            result = result.strip(" \t-*•")
            if not approach or len(approach) > 500:
                return None
            normalized = self._normalize_memory_text(approach)
            existing = next(
                (a for a in memory.approaches_tried
                 if self._normalize_memory_text(a.approach) == normalized),
                None,
            )
            if existing is None:
                existing = Attempt(approach=approach, result=result, status="tried")
                memory.approaches_tried.append(existing)
            elif result:
                append_result(existing, result)
            return existing

        def extract_inline_labeled_notes(content: str) -> None:
            """Handle compact one-line records supplied by a user at the start of a task."""
            labels = re.compile(
                r"(?P<label>approach(?:es)?\s+tried(?:\s*#?\d+)?|result|outcome|"
                r"next\s+steps?|cách\s+đã\s+thử|kết\s+quả(?:\s+thử)?|bước\s+tiếp\s+theo)\s*:\s*",
                re.IGNORECASE,
            )
            matches = list(labels.finditer(content))
            current_attempt: Attempt | None = None
            for index, match in enumerate(matches):
                value_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
                value = content[match.end():value_end].strip(" \t\n-;.")
                label = match.group("label").casefold()
                if not value:
                    continue
                if "approach" in label or "cách đã thử" in label:
                    current_attempt = add_attempt(value)
                elif label in {"result", "outcome", "kết quả", "kết quả thử"}:
                    if current_attempt is not None:
                        append_result(current_attempt, value)
                elif "next" in label or "bước tiếp theo" in label:
                    value_lines = value.splitlines()
                    listed_steps = [list_item.match(line) for line in value_lines]
                    if any(listed_steps):
                        for item in listed_steps:
                            if item:
                                append_step(item.group(1), memory)
                    else:
                        append_step(value, memory)

        for msg in messages:
            raw_content = msg.get("content", "")
            content = raw_content if isinstance(raw_content, str) else str(raw_content)
            # Existing memory is already carried in `memory`; parsing its rendered
            # text again would duplicate attempts and turn code examples into steps.
            if msg.get("type") == "system_memory" or (
                msg.get("role") == "system" and "=== WORKING MEMORY (PRESERVED) ===" in content
            ):
                continue
            # Tool output is evidence for the error field, not user-authored
            # notes. Parsing its JSON as prose creates noisy attempts/steps.
            if msg.get("role") == "tool":
                continue
            extract_inline_labeled_notes(content)
            current_attempt: Attempt | None = None
            in_next_steps = False
            in_code_block = False
            next_step_list_started = False

            for raw_line in content.splitlines():
                if raw_line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    if in_code_block:
                        in_next_steps = False
                    continue
                if in_code_block:
                    continue
                line = self._clean_memory_line(raw_line)
                if not line or line in {"---", "***", "___"}:
                    continue

                match = approach_label.match(line)
                if match:
                    current_attempt = add_attempt(match.group(1))
                    in_next_steps = False
                    continue

                match = result_label.match(line)
                if match:
                    result = match.group(1).strip()
                    if current_attempt is not None and result:
                        append_result(current_attempt, result)
                    in_next_steps = False
                    continue

                match = next_label.match(line)
                if match:
                    in_next_steps = True
                    next_step_list_started = False
                    trailing = match.group(1).strip()
                    if trailing:
                        item = list_item.match(trailing)
                        append_step(item.group(1) if item else trailing, memory)
                    continue

                if section_label.match(line):
                    in_next_steps = False
                    continue

                if in_next_steps:
                    item = list_item.match(line)
                    if item:
                        next_step_list_started = True
                        append_step(item.group(1), memory)
                    elif not next_step_list_started and not line.startswith(("`", "~")):
                        append_step(line, memory)
                    else:
                        in_next_steps = False
    
    def extract_working_memory(self, messages: list[dict]) -> WorkingMemory:
        """Extract critical context from message history."""
        memory = WorkingMemory()
        self._extract_attempts_and_next_steps(messages, memory)
        
        for msg in messages:
            content = msg.get("content", "") if isinstance(msg.get("content"), str) else str(msg.get("content", ""))
            role = msg.get("role", "")

            # The carried memory is merged separately by compact(); scanning
            # its rendered labels again can preserve stale/duplicated fields.
            if msg.get("type") == "system_memory" or (
                role == "system" and "=== WORKING MEMORY (PRESERVED) ===" in content
            ):
                continue
            if content.lstrip().startswith("[COMPACTED HISTORY]"):
                # This is only a conversation index; its bullet summaries are
                # not reliable issue or error evidence.
                continue

            # Explicit labels are more reliable than headings or explanatory
            # prose in assistant responses. Capture them before generic
            # fallback extraction can mistake a summary for the issue.
            if role in {"user", "assistant"}:
                for line in content.splitlines():
                    issue_match = re.match(r"\s*(?:issue|current issue|vấn đề|lỗi đang điều tra)\s*:\s*(.+)", line, re.I)
                    if not memory.current_issue and issue_match:
                        memory.current_issue = issue_match.group(1).strip()[:200]
                    error_match = re.match(r"\s*(?:error|exception|lỗi)\s*:\s*(.+)", line, re.I)
                    if not memory.error_details and error_match:
                        memory.error_details = error_match.group(1).strip()[:300]

            # Prefer an explicit issue label over a generic sentence about the task.
            # Prefer an explicit task/goal label; otherwise keep only a short
            # first sentence instead of copying a whole multi-field prompt.
            if not memory.goal and role == "user":
                goal_match = re.search(r"(?:^|\n)\s*(?:goal|objective|task|mục tiêu)\s*:\s*([^\n]+)", content, re.I)
                if goal_match:
                    memory.goal = goal_match.group(1).strip()[:200]
                elif re.search(r"(goal|objective|task|fix|solve|implement)", content, re.I):
                    first_sentence = re.split(r"(?<=[.!?])\s+", content.strip(), maxsplit=1)[0]
                    memory.goal = first_sentence[:200]
            
            # Extract issue/bug
            if re.search(r'(bug|error|issue|problem|fail|broken|crash|exception|timeout)', content, re.I):
                if not memory.current_issue and role == "user":
                    # Prefer user-reported evidence over assistant paraphrases.
                    match = re.search(r'([^.]*?(bug|error|issue|problem|fail|broken|crash|exception|timeout)[^.]*\.)', content, re.I)
                    if match and len(match.group(0)) < 200:
                        memory.current_issue = match.group(0).strip()
            
            # Extract a concise error line. Tool messages are often JSON
            # envelopes; inspect stdout/stderr values instead of preserving the
            # entire serialized payload.
            if not memory.error_details and role in {"user", "tool"}:
                error_sources = [content]
                if role == "tool":
                    try:
                        payload = json.loads(content)
                    except (TypeError, json.JSONDecodeError):
                        payload = None
                    if isinstance(payload, dict):
                        error_sources = [
                            str(payload.get(key, ""))
                            for key in ("stderr", "stdout", "error", "message")
                            if payload.get(key)
                        ]
                for source in error_sources:
                    for line in source.splitlines():
                        line = line.strip()
                        if re.search(r"\b(?:ValueError|TypeError|KeyError|IndexError|Exception|Traceback|FAILED|timeout)\b", line, re.I):
                            line = re.sub(r"^(?:issue|current issue|error|exception|lỗi)\s*:\s*", "", line, flags=re.I)
                            memory.error_details = line[:300]
                            break
                    if memory.error_details:
                        break
            
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
                if not f.startswith("//") and any(ext in f for ext in ['.py', '.js', '.ts', '.java', '.json', '.log', '.txt', '.yaml', '.yml']):
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
        
        # Clean duplicates already in carried memory as well as those in the
        # newly extracted notes. This matters when memory survives several
        # compaction cycles.
        unique_attempts: list[Attempt] = []
        for attempt in existing.approaches_tried:
            duplicate = next(
                (item for item in unique_attempts
                 if self._normalize_memory_text(item.approach) == self._normalize_memory_text(attempt.approach)),
                None,
            )
            if duplicate is None:
                unique_attempts.append(attempt)
            elif attempt.result and not duplicate.result:
                duplicate.result = attempt.result
        existing.approaches_tried = unique_attempts
        existing.next_steps = [
            step for index, step in enumerate(existing.next_steps)
            if is_actionable_step(step)
            and not any(self._normalize_memory_text(step) == self._normalize_memory_text(prev) for prev in existing.next_steps[:index])
        ]

        # Merge lists avoiding duplicates
        for a in extracted.approaches_tried:
            duplicate = next(
                (a2 for a2 in existing.approaches_tried
                 if self._normalize_memory_text(a2.approach) == self._normalize_memory_text(a.approach)),
                None,
            )
            if duplicate is None:
                existing.approaches_tried.append(a)
            elif a.result and not duplicate.result:
                duplicate.result = a.result
            elif a.result and self._normalize_memory_text(a.result) != self._normalize_memory_text(duplicate.result):
                duplicate.result = f"{duplicate.result} | {a.result}" if duplicate.result else a.result
        for s in extracted.next_steps:
            if is_actionable_step(s) and not any(self._normalize_memory_text(old) == self._normalize_memory_text(s) for old in existing.next_steps):
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
