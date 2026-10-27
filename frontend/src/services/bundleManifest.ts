/** Browser paths are preview metadata; the backend validates them independently. */
export function folderSupported() {
  return typeof document !== 'undefined' && 'webkitdirectory' in document.createElement('input')
}
export function bundleManifest(files: File[]) {
  return files.filter(f => !(f.webkitRelativePath || f.name).split('/').some(p => ['.DS_Store', 'Thumbs.db', '__MACOSX'].includes(p) || p.startsWith('._')))
    .map(file => ({ file, path: file.webkitRelativePath || file.name,
      error: !file.name.toLowerCase().endsWith('.csv') ? 'CSV only' : !file.size ? 'Empty file' : null }))
}
