/** A byte count in binary units, e.g. 4.7 MB (1024-based, as the Machine page has always shown). */
export const formatBytes = (bytes: number): string => {
  if (bytes <= 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(sizes.length - 1, Math.floor(Math.log(bytes) / Math.log(k)))
  return `${(bytes / Math.pow(k, i)).toFixed(i === 0 ? 0 : 1)} ${sizes[i]}`
}

/** An image size as `docker image ls` shows it: decimal units (1 MB = 1,000,000 bytes). */
export const formatImageSize = (bytes: number): string =>
  bytes >= 1e9 ? `${(bytes / 1e9).toFixed(2)} GB` : `${(bytes / 1e6).toFixed(1)} MB`
