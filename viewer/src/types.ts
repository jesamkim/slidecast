export interface Version {
  n: number;
  createdAt: string;
  // null while a freshly-uploaded version is still awaiting its thumbnail
  // from the thumbnail Lambda.
  thumbnailKey: string | null;
  sizeBytes: number;
  slideCount?: number;
  url?: string;
}
export interface Deck {
  deckId: string;
  title: string;
  tags: string[];
  status: "active" | "archived";
  currentVersion: number;
  versions: Version[];
  createdAt: string;
  updatedAt: string;
  group: string | null;
  alias: string | null;
}
export interface Group {
  groupId: string;
  name: string;
}
