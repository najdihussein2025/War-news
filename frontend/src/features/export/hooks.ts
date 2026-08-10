import { useMutation } from "@tanstack/react-query";
import { createExport } from "./api";

export const useCreateExport = () =>
  useMutation({
    mutationFn: createExport,
  });
