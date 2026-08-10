import { apiClient } from "../../lib/apiClient";
import type { NewsArticle } from "./types";

export const getReviewQueue = async (): Promise<NewsArticle[]> => {
  const response = await apiClient.get<NewsArticle[]>("/news/review-queue");
  return response.data;
};
