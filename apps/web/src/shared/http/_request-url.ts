export function backendRequestUrl(
  apiUrl: string,
  backendPath: string,
  requestUrl: string,
): string {
  const backendUrl = new URL(backendPath, apiUrl);
  if (!backendUrl.search) {
    backendUrl.search = new URL(requestUrl).search;
  }
  return backendUrl.toString();
}
