/* Gallery Runtime: reachability means "can this phone reach Stats", not
 * navigator.onLine. Cellular can be online while the private Pi is unreachable.
 */
export class GalleryNetwork {
  constructor({timeoutMs=3500, onChange=()=>{}} = {}) {
    this.timeoutMs = timeoutMs;
    this.onChange = onChange;
    this.reachable = null;
  }

  setReachable(value) {
    value = Boolean(value);
    if (this.reachable === value) return;
    this.reachable = value;
    this.onChange(value);
  }

  isReachable() {
    return this.reachable !== false;
  }

  async fetch(url, options = {}) {
    const timeoutMs = Number(options.timeoutMs || this.timeoutMs);
    const requestOptions = {...options};
    delete requestOptions.timeoutMs;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {
        cache:'no-store',
        credentials:'same-origin',
        ...requestOptions,
        signal:controller.signal,
      });
      this.setReachable(true);
      return response;
    } catch (error) {
      this.setReachable(false);
      if (error?.name === 'AbortError') {
        const timeout = new Error('Stats is unreachable from this network.');
        timeout.cause = error;
        throw timeout;
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  async json(url, options = {}) {
    const response = await this.fetch(url, options);
    const data = await response.json().catch(() => ({error:'Request failed. Reopen the gallery and try again.'}));
    if (!response.ok) {
      const error = new Error(data.error || 'Request failed');
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async probe() {
    try {
      await this.fetch('/gallery/api/access', {timeoutMs:2200});
      return true;
    } catch (error) {
      // An HTTP response proves Stats is reachable even when authorization
      // expired; only transport/timeouts make reachability false.
      return Boolean(error?.status);
    }
  }
}
