import type { ReactNode } from "react";

type ModalProps = {
  title: string;
  children: ReactNode;
  onClose: () => void;
};

export const Modal = ({ title, children, onClose }: ModalProps) => (
  <div className="fixed inset-0 flex items-center justify-center bg-slate-950/40 p-4">
    <section className="w-full max-w-lg rounded border border-slate-200 bg-white p-6 shadow-lg">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
        <button className="text-sm text-slate-500" onClick={onClose} type="button">
          Close
        </button>
      </div>
      <div className="mt-4">{children}</div>
    </section>
  </div>
);
