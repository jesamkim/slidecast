import type { Deck, Group, PublicDeck, ViewStats } from "./types";

export function createApi(baseUrl: string, getToken: () => string) {
  const auth = () => ({ Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" });
  const j = async (r: Response) => {
    if (!r.ok) throw new Error(`api ${r.status}`);
    return r.json();
  };
  return {
    async listDecks(status = "active", group?: string): Promise<Deck[]> {
      const q = new URLSearchParams({ status });
      if (group) q.set("group", group);
      const r = await fetch(`${baseUrl}/api/decks?${q}`, { headers: auth() });
      return (await j(r)).decks;
    },
    async listGroups(): Promise<Group[]> {
      return (await j(await fetch(`${baseUrl}/api/groups`, { headers: auth() }))).groups;
    },
    async createGroup(name: string) {
      return j(await fetch(`${baseUrl}/api/groups`, {
        method: "POST", headers: auth(), body: JSON.stringify({ name }),
      }));
    },
    async deleteGroup(groupId: string) {
      return j(await fetch(`${baseUrl}/api/groups/${groupId}`, { method: "DELETE", headers: auth() }));
    },
    async setGroup(id: string, groupId: string | null) {
      return j(await fetch(`${baseUrl}/api/decks/${id}/group`, {
        method: "PUT", headers: auth(), body: JSON.stringify({ groupId }),
      }));
    },
    async setAlias(id: string, alias: string | null) {
      return j(await fetch(`${baseUrl}/api/decks/${id}/alias`, {
        method: "PUT", headers: auth(), body: JSON.stringify({ alias }),
      }));
    },
    async resolve(alias: string): Promise<Deck> {
      return j(await fetch(`${baseUrl}/api/resolve/${alias}`, { headers: auth() }));
    },
    async getDeck(id: string): Promise<Deck> {
      return j(await fetch(`${baseUrl}/api/decks/${id}`, { headers: auth() }));
    },
    async createUpload(
      filename: string,
      title?: string,
      tags: string[] = [],
      group?: string | null,
    ) {
      const body: Record<string, unknown> = { filename, title, tags };
      if (group) body.group = group;
      return j(await fetch(`${baseUrl}/api/decks`, {
        method: "POST", headers: auth(), body: JSON.stringify(body),
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
    async share(id: string): Promise<{ token: string; url: string }> {
      return j(await fetch(`${baseUrl}/api/decks/${id}/share`, { method: "PUT", headers: auth() }));
    },
    async unshare(id: string) {
      return j(await fetch(`${baseUrl}/api/decks/${id}/share`, { method: "DELETE", headers: auth() }));
    },
    async republish(id: string) {
      return j(await fetch(`${baseUrl}/api/decks/${id}/share/republish`, { method: "POST", headers: auth() }));
    },
    async downloadUrl(id: string, format: "html" | "pdf", version?: number): Promise<{ downloadUrl: string }> {
      const q = new URLSearchParams({ format });
      if (version != null) q.set("version", String(version));
      return j(await fetch(`${baseUrl}/api/decks/${id}/download?${q}`, { headers: auth() }));
    },
    async getViews(id: string): Promise<ViewStats> {
      return j(await fetch(`${baseUrl}/api/decks/${id}/views`, { headers: auth() }));
    },
    async downloadViews(id: string, format: "csv" | "json") {
      const r = await fetch(`${baseUrl}/api/decks/${id}/views/export?format=${format}`, { headers: auth() });
      if (!r.ok) throw new Error(`export ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `${id}-views.${format}`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    },
    async uploadFile(url: string, file: Blob) {
      const r = await fetch(url, { method: "PUT", headers: { "Content-Type": "text/html" }, body: file });
      if (!r.ok) throw new Error(`upload ${r.status}`);
    },
  };
}

export async function fetchPublic(baseUrl: string, token: string): Promise<PublicDeck> {
  const r = await fetch(`${baseUrl}/api/public/${token}`);
  if (!r.ok) throw new Error(`public ${r.status}`);
  return r.json();
}
