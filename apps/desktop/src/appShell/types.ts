export type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

export type AsyncStatus = "idle" | "loading" | "success" | "empty" | "error";

export type SendChatTextOptions = {
  displayText?: string;
};
