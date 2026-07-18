import { describe, it, expect, vi, afterEach } from "vitest";
import {
    avatarSrcSet,
    extractFileId,
    mediaUrl,
    pickAvatarVariant,
    resolveMediaSrc,
} from "@/lib/media";

afterEach(() => {
    vi.unstubAllGlobals();
});

describe("mediaUrl", () => {
    it("returns the original-file URL when no variant is given", () => {
        expect(mediaUrl("abc")).toBe("/api/media/v1/files/abc");
    });

    it("includes the variant in the path when provided", () => {
        expect(mediaUrl("abc", "thumb_96")).toBe("/api/media/v1/files/abc/thumb_96");
    });
});

describe("resolveMediaSrc", () => {
    it("returns undefined for empty input", () => {
        expect(resolveMediaSrc(undefined)).toBeUndefined();
        expect(resolveMediaSrc(null)).toBeUndefined();
        expect(resolveMediaSrc("")).toBeUndefined();
    });

    it("passes through absolute / blob / data URLs unchanged", () => {
        expect(resolveMediaSrc("https://example.com/x.png")).toBe(
            "https://example.com/x.png",
        );
        expect(resolveMediaSrc("blob:abc")).toBe("blob:abc");
        expect(resolveMediaSrc("data:image/png;base64,AA")).toBe(
            "data:image/png;base64,AA",
        );
    });

    it("expands a bare UUID to the canonical media URL", () => {
        const id = "11111111-2222-3333-4444-555555555555";
        expect(resolveMediaSrc(id)).toBe(`/api/media/v1/files/${id}`);
    });

    it("leaves an existing relative path alone", () => {
        expect(resolveMediaSrc("/api/media/v1/files/x")).toBe(
            "/api/media/v1/files/x",
        );
    });
});

describe("extractFileId", () => {
    it("pulls the UUID out of a relative URL", () => {
        const id = "11111111-2222-3333-4444-555555555555";
        expect(extractFileId(`/api/media/v1/files/${id}`)).toBe(id);
    });

    it("works with an absolute URL", () => {
        const id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
        expect(extractFileId(`https://host/api/media/v1/files/${id}`)).toBe(id);
    });

    it("returns null for legacy / external URLs", () => {
        expect(extractFileId("https://i.pravatar.cc/150?u=foo")).toBeNull();
    });

    it("returns null for empty input", () => {
        expect(extractFileId(null)).toBeNull();
        expect(extractFileId(undefined)).toBeNull();
    });
});

describe("pickAvatarVariant", () => {
    it("rounds up to thumb_32 for the smallest sizes at DPR=1", () => {
        vi.stubGlobal("window", { devicePixelRatio: 1 } as any);
        expect(pickAvatarVariant(24)).toBe("thumb_32");
        expect(pickAvatarVariant(32)).toBe("thumb_32");
    });

    it("returns thumb_96 for medium sizes at DPR=1", () => {
        vi.stubGlobal("window", { devicePixelRatio: 1 } as any);
        expect(pickAvatarVariant(48)).toBe("thumb_96");
        expect(pickAvatarVariant(96)).toBe("thumb_96");
    });

    it("escalates to thumb_256 on retina (DPR=2) for medium sizes", () => {
        vi.stubGlobal("window", { devicePixelRatio: 2 } as any);
        // 48 * 2 = 96 → thumb_96 still fits exactly
        expect(pickAvatarVariant(48)).toBe("thumb_96");
        // 96 * 2 = 192 → only thumb_256 is large enough
        expect(pickAvatarVariant(96)).toBe("thumb_256");
    });

    it("clamps DPR to 3 to avoid runaway choices on weird displays", () => {
        vi.stubGlobal("window", { devicePixelRatio: 5 } as any);
        // 32 * min(5, 3) = 96 → thumb_96 (clamped)
        expect(pickAvatarVariant(32)).toBe("thumb_96");
    });
});

describe("avatarSrcSet", () => {
    it("emits 32w / 96w / 256w descriptors", () => {
        const set = avatarSrcSet("xyz");
        expect(set).toContain("/api/media/v1/files/xyz/thumb_32 32w");
        expect(set).toContain("/api/media/v1/files/xyz/thumb_96 96w");
        expect(set).toContain("/api/media/v1/files/xyz/thumb_256 256w");
    });
});
