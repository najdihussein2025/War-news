import type { NewsArticle } from "../types";

export const ReviewQueueTable = ({ articles }: { articles: NewsArticle[] }) => (
  <div className="overflow-hidden rounded border border-slate-200 bg-white">
    <table className="min-w-full divide-y divide-slate-200 text-sm">
      <thead className="bg-slate-50 text-left text-slate-600">
        <tr>
          <th className="px-4 py-3 font-medium">Title</th>
          <th className="px-4 py-3 font-medium">Status</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {articles.map((article) => (
          <tr key={article.id}>
            <td className="px-4 py-3 text-slate-950">{article.title}</td>
            <td className="px-4 py-3 text-slate-600">{article.status}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);
