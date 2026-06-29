export const productCopy = {
  displayName: "本地陪伴体",
  promise: "我会长期记住重要的事，陪你把每天接上；记忆留在本机，可查看、可撤回。",
  coreValues: [
    {
      title: "长期陪伴",
      description: "下次再见时，我能接住你之前说过的重要事。",
    },
    {
      title: "本地记忆",
      description: "值得留下的内容优先保存在这台电脑里。",
    },
    {
      title: "记忆可控",
      description: "记住了什么、为什么记住、能不能撤回，都让你看得见。",
    },
  ],
  firstUse: {
    title: "今天想让我从哪里陪你继续？",
    description: "只说一件正在发生的事就可以开始，其他内容以后再补。",
    question: "今天想让我从哪里陪你继续？",
    placeholder: "例如：我最近在准备一件重要的事，想有人帮我接着记住。",
    submitLabel: "开始聊天",
    skipLabel: "先直接聊",
    completedMessage: "我会按规则整理这次内容，你之后可以在记忆里查看和撤回。",
  },
  memoryPage: {
    title: "我的记忆",
    description: "这里能看到我记住的内容、来源和状态，也能撤回不想留下的记忆。",
    searchPlaceholder: "搜索我记住的事",
    activeSectionTitle: "正在使用的记忆",
    pendingSectionTitle: "待确认的记忆",
    recentHistoryTitle: "最近撤回或跳过的记忆",
    emptyState: "还没有留下记忆。和我聊聊，或主动告诉我一件希望记住的事。",
  },
  chatPage: {
    title: "聊天",
    description: "直接和我说话；重要的事我会按规则整理，之后可在记忆里查看和撤回。",
    inputPlaceholder: "和我说说现在发生的事...",
    quickPrompts: [
      "我今天有点累",
      "记住我最近在准备一件重要的事",
      "明天提醒我继续这件事",
      "帮我回顾今天",
    ],
  },
} as const;
