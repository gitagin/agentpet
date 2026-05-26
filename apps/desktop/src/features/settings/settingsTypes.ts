export type LastIndexRun = {
  vaultId: string;
  jobId: string;
  status: string;
  filesSeen?: number;
  filesIndexed?: number;
};
