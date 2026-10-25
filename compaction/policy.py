"""Compaction policy - when to compact and what to keep/drop."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CompactionPolicy:
    """Policy defining compaction triggers and retention rules."""
    # Token-based trigger
    max_context_tokens: int = 8000
    compact_threshold_ratio: float = 0.7  # Trigger when usage > 70% of max
    # Message-based trigger
    max_messages: int = 30
    compact_on_message_threshold: int = 20
    
    # Retention rules
    keep_recent_turns: int = 4  # Always keep last N turns verbatim
    keep_system_messages: bool = True
    keep_recent_tool_results: int = 2
    
    # Selective compaction rules
    summarize_old_turns: bool = True
    extract_working_memory: bool = True
    drop_redundant_acks: bool = True
    truncate_large_logs: bool = True
    max_log_lines_to_keep: int = 30
    
    def should_compact(self, current_tokens: int, message_count: int) -> bool:
        """Determine if compaction should be triggered."""
        token_trigger = current_tokens > (self.max_context_tokens * self.compact_threshold_ratio)
        message_trigger = message_count >= self.compact_on_message_threshold
        return token_trigger or message_trigger
    
    @property
    def threshold_tokens(self) -> int:
        return int(self.max_context_tokens * self.compact_threshold_ratio)
