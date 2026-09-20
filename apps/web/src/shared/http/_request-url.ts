export function backendRequestUrl(
  apiUrl: string,
  backendPath: string,
  requestUrl: string,
): string {
  return `${apiUrl}${backendPath}${new URL(requestUrl).search}`;
}
