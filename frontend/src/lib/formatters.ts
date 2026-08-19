import { APP_TIME_ZONE } from "./localDate";

const DATE_ONLY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

const toDate = (value: string | Date): Date =>
  value instanceof Date ? value : new Date(value);

/** Calendar dates (YYYY-MM-DD) are stored without timezone; anchor at noon UTC to avoid day shifts. */
const calendarDateToReferenceInstant = (value: string): Date => {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day, 12));
};

export const formatDateTime = (value: string | Date) =>
  new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: APP_TIME_ZONE,
  }).format(toDate(value));

export const formatClockTime = (value: string | Date) =>
  new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: APP_TIME_ZONE,
  }).format(toDate(value));

const relativeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export const formatRelativeTime = (value: string | null) => {
  if (!value) {
    return "Never";
  }

  const diffMinutes = Math.round((new Date(value).getTime() - Date.now()) / 60000);

  if (Math.abs(diffMinutes) < 60) {
    return relativeFormatter.format(diffMinutes, "minute");
  }

  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) {
    return relativeFormatter.format(diffHours, "hour");
  }

  const diffDays = Math.round(diffHours / 24);
  if (Math.abs(diffDays) < 30) {
    return relativeFormatter.format(diffDays, "day");
  }

  return relativeFormatter.format(Math.round(diffDays / 30), "month");
};

export const formatDate = (value: string | Date) => {
  const instant =
    typeof value === "string" && DATE_ONLY_PATTERN.test(value)
      ? calendarDateToReferenceInstant(value)
      : toDate(value);

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeZone: APP_TIME_ZONE,
  }).format(instant);
};
