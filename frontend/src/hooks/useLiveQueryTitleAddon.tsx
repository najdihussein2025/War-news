import { useContext, useEffect } from "react";
import { ShellContext } from "../app/AppShell";
import { LiveQueryIndicator } from "../components/LiveQueryIndicator";

export const useLiveQueryTitleAddon = (
  dataUpdatedAt: number,
  isFetching: boolean,
) => {
  const shell = useContext(ShellContext);

  useEffect(() => {
    shell?.setTitleAddon(
      <LiveQueryIndicator
        dataUpdatedAt={dataUpdatedAt}
        isFetching={isFetching}
      />,
    );
    return () => shell?.setTitleAddon(null);
  }, [shell, dataUpdatedAt, isFetching]);
};
