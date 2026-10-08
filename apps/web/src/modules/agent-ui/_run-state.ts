export function shouldClearTransientRunError(
  status: string | undefined,
): boolean {
  return status === "succeeded";
}
