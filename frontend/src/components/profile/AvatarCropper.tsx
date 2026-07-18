import React, { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Cropper, { type Area } from "react-easy-crop";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";

interface AvatarCropperProps {
    file: File | null;
    open: boolean;
    onCancel: () => void;
    onConfirm: (cropped: Blob) => void;
}

const OUTPUT_SIZE = 1024;

/**
 * Square / round avatar cropper. Returns a JPEG Blob (1024×1024 max) so the
 * server's avatar policy (8 MB, 256² thumbnail) has plenty of pixels to work
 * with while keeping the upload small.
 */
export const AvatarCropper: React.FC<AvatarCropperProps> = ({
    file,
    open,
    onCancel,
    onConfirm,
}) => {
    const { t } = useTranslation();
    const [imageSrc, setImageSrc] = useState<string | null>(null);
    const [crop, setCrop] = useState({ x: 0, y: 0 });
    const [zoom, setZoom] = useState(1);
    const [croppedArea, setCroppedArea] = useState<Area | null>(null);
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        if (!file) {
            setImageSrc(null);
            return;
        }
        const url = URL.createObjectURL(file);
        setImageSrc(url);
        setCrop({ x: 0, y: 0 });
        setZoom(1);
        setCroppedArea(null);
        return () => {
            URL.revokeObjectURL(url);
        };
    }, [file]);

    const handleCropComplete = useCallback((_: Area, areaPixels: Area) => {
        setCroppedArea(areaPixels);
    }, []);

    const handleConfirm = useCallback(async () => {
        if (!imageSrc || !croppedArea) return;
        setBusy(true);
        try {
            const blob = await renderCrop(imageSrc, croppedArea);
            onConfirm(blob);
        } finally {
            setBusy(false);
        }
    }, [imageSrc, croppedArea, onConfirm]);

    return (
        <Dialog open={open} onOpenChange={(v) => { if (!v) onCancel(); }}>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>{t("profile.cropAvatar", "Обрежьте аватар")}</DialogTitle>
                </DialogHeader>

                <div className="relative w-full h-72 bg-black/80 rounded-md overflow-hidden">
                    {imageSrc && (
                        <Cropper
                            image={imageSrc}
                            crop={crop}
                            zoom={zoom}
                            aspect={1}
                            cropShape="round"
                            showGrid={false}
                            onCropChange={setCrop}
                            onZoomChange={setZoom}
                            onCropComplete={handleCropComplete}
                        />
                    )}
                </div>

                <div className="px-1">
                    <Slider
                        value={[zoom]}
                        min={1}
                        max={3}
                        step={0.01}
                        onValueChange={(v) => setZoom(v[0] ?? 1)}
                    />
                </div>

                <DialogFooter>
                    <Button variant="outline" onClick={onCancel} disabled={busy}>
                        {t("common.cancel", "Отмена")}
                    </Button>
                    <Button onClick={handleConfirm} disabled={busy || !croppedArea}>
                        {t("profile.applyCrop", "Применить")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};


function loadImage(src: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.crossOrigin = "anonymous";
        img.onload = () => resolve(img);
        img.onerror = (e) => reject(e);
        img.src = src;
    });
}

async function renderCrop(imageSrc: string, area: Area): Promise<Blob> {
    const img = await loadImage(imageSrc);
    const target = Math.min(OUTPUT_SIZE, Math.round(area.width));
    const canvas = document.createElement("canvas");
    canvas.width = target;
    canvas.height = target;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("canvas 2d context unavailable");

    ctx.drawImage(
        img,
        area.x,
        area.y,
        area.width,
        area.height,
        0,
        0,
        target,
        target,
    );

    return new Promise<Blob>((resolve, reject) => {
        canvas.toBlob(
            (blob) => (blob ? resolve(blob) : reject(new Error("toBlob returned null"))),
            "image/jpeg",
            0.9,
        );
    });
}

export default AvatarCropper;
