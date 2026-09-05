/**
 * Shared date formatting for the renderer.
 *
 * Five feature/views used to carry private copy-pasted `formatDate`
 * implementations that drifted apart (different locales options, different
 * fallback texts, different invalid-value handling).  This module keeps one
 * implementation while preserving each call site's historical output.
 */

export type DateFormatStyle = "monthDay" | "mediumDateTime" | "dateTime";

export type FormatDateOptions = {
  /** Output shape. Defaults to `dateTime` (MM-DD HH:mm, 24h). */
  style?: DateFormatStyle;
  /** Shown when the value is null/undefined/empty. Defaults to "时间未记录". */
  fallback?: string;
  /** Shown when the value cannot be parsed; defaults to `fallback`. */
  invalidFallback?: string;
};

const zhCnDateTime = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const zhCnMediumDateTime = new Intl.DateTimeFormat("zh-CN", {
  dateStyle: "medium",
  timeStyle: "short",
});

const zhCnMonthDay = new Intl.DateTimeFormat("zh-CN", {
  month: "short",
  day: "numeric",
});

export function formatDate(value?: string | null, options: FormatDateOptions = {}): string {
  const { style = "dateTime", fallback = "时间未记录", invalidFallback = fallback } = options;
  if (!value) {
    return fallback;
  }
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return invalidFallback;
  }
  const date = new Date(timestamp);
  if (style === "monthDay") {
    return zhCnMonthDay.format(date);
  }
  if (style === "mediumDateTime") {
    return zhCnMediumDateTime.format(date);
  }
  return zhCnDateTime.format(date);
}
