export type NewsArticle = {
  id: string;
  title: string;
  status: "pending" | "approved" | "rejected";
};
