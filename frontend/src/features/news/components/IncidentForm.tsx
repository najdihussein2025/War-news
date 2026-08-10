export const IncidentForm = () => (
  <form className="rounded border border-slate-200 bg-white p-4">
    <label className="block text-sm font-medium text-slate-700">
      Incident notes
      <textarea className="mt-1 min-h-32 w-full rounded border border-slate-300 px-3 py-2" />
    </label>
  </form>
);
