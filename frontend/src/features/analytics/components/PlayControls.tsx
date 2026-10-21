import type { Dispatch, SetStateAction } from "react";

export type Playback = {
  active: boolean;
  playing: boolean;
  preparing: boolean;
  progress: number;
  index: number;
  labels: string[];
};

type Props = {
  state: Playback;
  setState: Dispatch<SetStateAction<Playback>>;
  onStart: () => void;
  onStop: () => void;
  disabled?: boolean;
};

export const PlayControls = ({ state, setState, onStart, onStop, disabled }: Props) => {
  const btn = "h-9 rounded-md border border-border bg-surface-raised px-3 text-small font-medium shadow-raised hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring disabled:opacity-50";
  if (!state.active) {
    return <button type="button" className={btn} onClick={onStart} disabled={disabled} aria-label="Play the map through the selected period">▶ Play</button>;
  }
  return (
    <div className="flex items-center gap-2 rounded-md border border-border bg-surface-raised/95 p-1.5 shadow-raised">
      {state.preparing ? (
        <span className="px-2 text-small" role="status">Loading frames {Math.round(state.progress * 100)}%</span>
      ) : (
        <>
          <button type="button" className={btn} onClick={() => setState((s) => ({ ...s, playing: !s.playing }))} aria-label={state.playing ? "Pause" : "Play"}>{state.playing ? "❚❚" : "▶"}</button>
          <input type="range" min={0} max={Math.max(0, state.labels.length - 1)} value={state.index} aria-label="Playback position"
            onChange={(e) => setState((s) => ({ ...s, playing: false, index: Number(e.target.value) }))} className="w-48" />
          <span className="min-w-24 text-caption tabular-nums">{state.labels[state.index]}</span>
        </>
      )}
      <button type="button" className={btn} onClick={onStop} aria-label="Stop playback and return to the full period">■ Stop</button>
    </div>
  );
};
