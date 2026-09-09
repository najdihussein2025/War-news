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

type EventDateTime = {
  event_date: string;
  event_time: string | null;
};

const calendarDateToUtcMidnight = (value: string): Date => {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
};

const eventToInstant = (value: EventDateTime): Date | null => {
  if (!value.event_time) {
    return null;
  }

  const [year, month, day] = value.event_date.split("-").map(Number);
  const [hour = 0, minute = 0, second = 0] = value.event_time
    .split(":")
    .map(Number);
  return new Date(Date.UTC(year, month - 1, day, hour, minute, second));
};

const formatDayGap = (days: number) => {
  if (days === 0) {
    return "same day";
  }
  if (days === 1) {
    return "1 day apart";
  }
  return `${days} days apart`;
};

export const formatTimeGap = (a: EventDateTime, b: EventDateTime) => {
  const aInstant = eventToInstant(a);
  const bInstant = eventToInstant(b);

  if (!aInstant || !bInstant) {
    const dateOnlyDiffDays = Math.round(
      Math.abs(
        calendarDateToUtcMidnight(a.event_date).getTime() -
          calendarDateToUtcMidnight(b.event_date).getTime(),
      ) / 86_400_000,
    );
    return formatDayGap(dateOnlyDiffDays);
  }

  const diffMinutes = Math.round(
    Math.abs(aInstant.getTime() - bInstant.getTime()) / 60_000,
  );

  if (diffMinutes === 0) {
    return "same time";
  }
  if (diffMinutes < 60) {
    return diffMinutes === 1 ? "1 minute apart" : `${diffMinutes} minutes apart`;
  }

  if (diffMinutes < 1_440) {
    const hours = Math.floor(diffMinutes / 60);
    const minutes = diffMinutes % 60;
    if (minutes === 0) {
      return hours === 1 ? "1 hour apart" : `${hours} hours apart`;
    }
    return `${hours}h ${minutes}m apart`;
  }

  return formatDayGap(Math.round(diffMinutes / 1_440));
};
