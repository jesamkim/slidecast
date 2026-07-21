import type { Deck } from "./types";

export function createApi(baseUrl: string, getToken: () => string) {
  const auth = () => ({ Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" });
  const j = async (r: Response) => {
    if (!r.ok) throw new Error(`api ${r.status}`);
    return r.json();
  };
  return {
    async listDecks(status = "active"): Promise<Deck[]> {
      const r = await fetch(`${baseUrl}/api/decks?status=${status}`, { headers: auth() });
      return (await j(r)).decks;
    },
    async getDeck(id: string): Promise<Deck> {
      return j(await fetch(`${baseUrl}/api/decks/${id}`, { headers: auth() }));
    },
    async createUpload(filename: string, title?: string, tags: string[] = []) {
      return j(await fetch(`${baseUrl}/api/decks`, {
        method: "POST", headers: auth(), body: JSON.stringify({ filename, title, tags }),
      }));
    },
    async updateUpload(id: string) {
      return j(await fetch(`${baseUrl}/api/decks/${id}`, { method: "PUT", headers: auth() }));
    },
    async setCurrent(id: string, n: number) {
      return j(await fetch(`${baseUrl}/api/decks/${id}/current`, {
        method: "PUT", headers: auth(), body: JSON.stringify({ version: n }),
      }));
    },
    async softDelete(id: string) {
      return j(await fetch(`${baseUrl}/api/decks/${id}`, { method: "DELETE", headers: auth() }));
    },
    async restore(id: string) {
      return j(await fetch(`${baseUrl}/api/decks/${id}/restore`, { method: "POST", headers: auth() }));
    },
    async hardDelete(id: string) {
      return j(await fetch(`${baseUrl}/api/decks/${id}?hard=true`, { method: "DELETE", headers: auth() }));
    },
    async uploadFile(url: string, file: Blob) {
      const r = await fetch(url, { method: "PUT", headers: { "Content-Type": "text/html" }, body: file });
      if (!r.ok) throw new Error(`upload ${r.status}`);
    },
  };
}
