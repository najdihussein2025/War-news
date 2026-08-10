import { ReviewQueueTable } from "../components/ReviewQueueTable";
import { useReviewQueue } from "../hooks";

export const ReviewQueuePage = () => {
  const { data = [], isLoading } = useReviewQueue();

  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <h1 className="text-2xl font-semibold text-slate-950">Review Queue</h1>
      <div className="mt-6">
        {isLoading ? <p>Loading...</p> : <ReviewQueueTable articles={data} />}
      </div>
    </main>
  );
};
