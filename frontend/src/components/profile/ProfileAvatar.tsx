import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Camera } from "lucide-react";
import { resolveMediaSrc } from "@/lib/media";
import { AvatarCropper } from "@/components/profile/AvatarCropper";

interface ProfileAvatarProps {
    avatarUrl?: string;
    firstName?: string;
    /**
     * Receives a Blob for the cropped avatar (JPEG, ≤1024×1024). Accepts a
     * File for back-compat with callers that haven't migrated yet.
     */
    onAvatarChange: (file: Blob) => void;
}

export const ProfileAvatar: React.FC<ProfileAvatarProps> = ({ avatarUrl, firstName, onAvatarChange }) => {
    const { t } = useTranslation();
    const [previewBlobUrl, setPreviewBlobUrl] = useState<string | null>(null);
    const [pendingFile, setPendingFile] = useState<File | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        return () => {
            if (previewBlobUrl) URL.revokeObjectURL(previewBlobUrl);
        };
    }, [previewBlobUrl]);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        setPendingFile(file);
        // Reset the input so the same file can be re-selected later.
        e.target.value = "";
    };

    const triggerFileInput = () => fileInputRef.current?.click();

    const handleCropConfirm = (cropped: Blob) => {
        if (previewBlobUrl) URL.revokeObjectURL(previewBlobUrl);
        setPreviewBlobUrl(URL.createObjectURL(cropped));
        setPendingFile(null);
        onAvatarChange(cropped);
    };

    const initials = firstName ? firstName.charAt(0).toUpperCase() : "U";
    const displaySrc = previewBlobUrl ?? resolveMediaSrc(avatarUrl);

    return (
        <>
            <div className="flex flex-col items-center space-y-4">
                <div className="relative group cursor-pointer" onClick={triggerFileInput}>
                    <Avatar className="w-32 h-32 border-4 border-background shadow-xl">
                        <AvatarImage src={displaySrc} className="object-cover" />
                        <AvatarFallback className="text-4xl">{initials}</AvatarFallback>
                    </Avatar>
                    <div className="absolute inset-0 bg-black/40 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                        <Camera className="text-white w-8 h-8" />
                    </div>
                </div>
                <Input
                    type="file"
                    ref={fileInputRef}
                    className="hidden"
                    accept="image/*"
                    onChange={handleFileChange}
                />
                <Button variant="outline" size="sm" onClick={triggerFileInput}>
                    {t('profile.changeAvatar')}
                </Button>
            </div>

            <AvatarCropper
                file={pendingFile}
                open={pendingFile !== null}
                onCancel={() => setPendingFile(null)}
                onConfirm={handleCropConfirm}
            />
        </>
    );
};
