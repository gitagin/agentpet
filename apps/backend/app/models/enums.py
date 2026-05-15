try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class MessageStatus(StrEnum):
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NoteStatus(StrEnum):
    INDEXED = "indexed"
    DELETED = "deleted"
    FAILED = "failed"


class MemoryProposalType(StrEnum):
    PREFERENCE = "preference"
    FACT = "fact"
    EVENT = "event"
    GOAL = "goal"
    RULE = "rule"


class MemoryProposalStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    FAILED = "failed"


class MemoryFactStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    ARCHIVED = "archived"
    REJECTED = "rejected"


class TaskStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    CANCELLED = "cancelled"


class ReminderStatus(StrEnum):
    SCHEDULED = "scheduled"
    UNSCHEDULED = "unscheduled"
    TRIGGERED = "triggered"
    CANCELLED = "cancelled"
    FAILED = "failed"


class IndexJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class IndexJobType(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"


class AgentIntent(StrEnum):
    CHAT = "chat"
    SEARCH_MEMORY = "search_memory"
    PROPOSE_MEMORY = "propose_memory"
    MANAGE_WIKI = "manage_wiki"
    CREATE_TASK = "create_task"


class AgentId(StrEnum):
    CHAT_AGENT = "chat_agent"
    SEMANTIC_ANALYSIS_AGENT = "semantic_analysis_agent"
    DIARY_MEMORY_EXTRACTOR_AGENT = "diary_memory_extractor_agent"
    MEMORY_RETRIEVAL_AGENT = "memory_retrieval_agent"
    KNOWLEDGE_RETRIEVAL_AGENT = "knowledge_retrieval_agent"
    WIKI_MANAGER_AGENT = "wiki_manager_agent"
    MEMORY_PROPOSAL_AGENT = "memory_proposal_agent"
    CONTINUITY_AGENT = "continuity_agent"
    TASK_AGENT = "task_agent"


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolCallStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    DENIED = "denied"


class AuditResult(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    FAILED = "failed"


class AuditActor(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
