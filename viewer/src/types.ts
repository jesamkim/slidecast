export interface Version {
  n: number;
  createdAt: string;
  // null while a freshly-uploaded version is still awaiting its thumbnail
  // from the thumbnail Lambda.
  thumbnailKey: string | null;
  sizeBytes: number;
  slideCount?: number;
  url?: string;
  pdfKey: string | null;
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
  publicToken: string | null;
  viewCount?: number;
}
export interface ViewStats {
  total: number;
  byDay: { date: string; count: number }[];
}
export interface Group {
  groupId: string;
  name: string;
}
export interface PublicDeck {
  title: string;
  htmlUrl: string;
}
