import { useParams } from "react-router-dom";
import { IncidentForm } from "../components/IncidentForm";

export const IncidentDetailPage = () => {
  const { incidentId } = useParams();

  return (
    <main className="mx-auto max-w-4xl px-6 py-8">
      <h1 className="text-2xl font-semibold text-slate-950">Incident {incidentId}</h1>
      <div className="mt-6">
        <IncidentForm />
      </div>
    </main>
  );
};
