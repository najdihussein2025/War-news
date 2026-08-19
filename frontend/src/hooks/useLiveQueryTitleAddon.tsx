import { useContext, useEffect } from "react";
import { ShellContext } from "../app/AppShell";
import { LiveQueryIndicator } from "../components/LiveQueryIndicator";

export const useLiveQueryTitleAddon = (
  latestIncidentAt: string | null,
  isFetching: boolean,
) => {
  const shell = useContext(ShellContext);

  useEffect(() => {
    shell?.setTitleAddon(
      <LiveQueryIndicator
        latestIncidentAt={latestIncidentAt}
        isFetching={isFetching}
      />,
    );
    return () => shell?.setTitleAddon(null);
  }, [shell, latestIncidentAt, isFetching]);
};
