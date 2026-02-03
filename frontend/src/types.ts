export type CheckRequest = {
  address: string;
  country?: string;
  lat?: number | null;
  lon?: number | null;
};

export type CheckResult = Record<string, any> & {
  ok: boolean;
  input_address: string;
  lat?: number | null;
  lon?: number | null;
};

export type CheckLog = Record<string, any> & {
  id: number;
  created_at: string;
  address: string;
};
