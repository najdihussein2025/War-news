export const APP_TIME_ZONE = "Asia/Beirut";

export const getBeirutDate = (dayOffset = 0, now = new Date()): string => {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: APP_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const localCalendarDate = new Date(Date.UTC(
    Number(values.year),
    Number(values.month) - 1,
    Number(values.day) + dayOffset,
    12,
  ));
  return localCalendarDate.toISOString().slice(0, 10);
};
