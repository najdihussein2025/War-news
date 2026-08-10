import { useQuery } from "@tanstack/react-query";
import { getReviewQueue } from "./api";

export const useReviewQueue = () =>
  useQuery({
    queryKey: ["news", "review-queue"],
    queryFn: getReviewQueue,
  });
