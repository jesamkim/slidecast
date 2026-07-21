export interface Version {
  n: number;
  createdAt: string;
  thumbnailKey: string;
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
}
