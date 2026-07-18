import * as React from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import {
    AvatarSize,
    extractFileId,
    mediaUrl,
    pickAvatarVariant,
    resolveMediaSrc,
} from "@/lib/media";

interface UserAvatarProps {
    /** Direct media-service file id (UUID). Preferred — yields srcset retina handling. */
    fileId?: string | null;
    /** Stored avatar URL (legacy). May be a relative `/api/media/v1/files/{id}` or external URL. */
    url?: string | null;
    /** Display name — used to derive fallback initials. */
    name?: string | null;
    /** CSS render size in px. Component picks the smallest crisp variant for the device DPR. */
    size?: AvatarSize;
    className?: string;
}

const SIZE_TO_CLASS: Record<AvatarSize, string> = {
    24: "w-6 h-6 text-[10px]",
    32: "w-8 h-8 text-xs",
    48: "w-12 h-12 text-sm",
    64: "w-16 h-16 text-base",
    96: "w-24 h-24 text-2xl",
    128: "w-32 h-32 text-3xl",
    256: "w-64 h-64 text-5xl",
};

function initialsFor(name?: string | null): string {
    if (!name) return "U";
    const parts = name.trim().split(/\s+/);
    if (parts.length === 0) return "U";
    if (parts.length === 1) return parts[0].charAt(0).toUpperCase();
    return (parts[0].charAt(0) + parts[1].charAt(0)).toUpperCase();
}

/**
 * Single-stop avatar component. Uses media-service variants when given a
 * ``fileId`` (or a URL we can mine an id out of), otherwise falls back to
 * whatever URL was stored. Variants that haven't been generated yet 404
 * cleanly — Radix's Image primitive then surfaces the AvatarFallback.
 */
export const UserAvatar: React.FC<UserAvatarProps> = ({
    fileId,
    url,
    name,
    size = 32,
    className,
}) => {
    const id = fileId ?? extractFileId(url);
    let src: string | undefined;
    let srcSet: string | undefined;

    if (id) {
        const variant = pickAvatarVariant(size);
        src = mediaUrl(id, variant);
        srcSet = [
            `${mediaUrl(id, "thumb_32")} 1x`,
            `${mediaUrl(id, size <= 32 ? "thumb_96" : "thumb_256")} 2x`,
        ].join(", ");
    } else {
        src = resolveMediaSrc(url);
    }

    return (
        <Avatar className={cn(SIZE_TO_CLASS[size], className)}>
            {src ? <AvatarImage src={src} srcSet={srcSet} className="object-cover" /> : null}
            <AvatarFallback>{initialsFor(name)}</AvatarFallback>
        </Avatar>
    );
};

UserAvatar.displayName = "UserAvatar";
