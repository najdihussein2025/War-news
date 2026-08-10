export const formatDateTime = (value: string | Date) =>
  new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));

const relativeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const mockNow = new Date("2026-08-10T12:00:00+03:00");

export const formatRelativeTime = (value: string | null) => {
  if (!value) {
    return "Never";
  }

  const diffMinutes = Math.round((new Date(value).getTime() - mockNow.getTime()) / 60000);

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

export const formatDate = (value: string | Date) =>
  new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
  }).format(new Date(value));
