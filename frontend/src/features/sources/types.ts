export type Source = {
  id: number;
  type: "telegram" | "twitter" | "facebook" | "website" | "api" | "manual" | "other";
  name: string;
  is_active: boolean;
};
