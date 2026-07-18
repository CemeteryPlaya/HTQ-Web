interface OptimizedImageProps {
  /** WebP image path (e.g., "/images/panels1.webp") */
  src: string;
  alt: string;
  width: number;
  height: number;
  /** WebP srcset (e.g., "/images/panels1-400w.webp 400w, /images/panels1.webp 800w") */
  srcSet?: string;
  /** AVIF srcset — auto-derived from srcSet/src if omitted (.webp → .avif) */
  avifSrcSet?: string;
  /** By default AVIF is preferred. Set to false to prefer WebP when AVIF is larger. */
  preferAvif?: boolean;
  sizes?: string;
  loading?: "lazy" | "eager";
  fetchPriority?: "high" | "low" | "auto";
  decoding?: "sync" | "async" | "auto";
  className?: string;
}

/** Derives AVIF path/srcset by replacing .webp → .avif */
function toAvif(webpValue: string): string {
  return webpValue.replace(/\.webp/g, ".avif");
}

export function OptimizedImage({
  src,
  alt,
  width,
  height,
  srcSet,
  avifSrcSet,
  preferAvif = true,
  sizes,
  loading = "lazy",
  fetchPriority = "auto",
  decoding = "async",
  className,
}: OptimizedImageProps) {
  const resolvedAvifSrcSet = avifSrcSet || (srcSet ? toAvif(srcSet) : toAvif(src));
  const resolvedAvifSrc = toAvif(src);
  const webpSource = srcSet ? (
    <source
      type="image/webp"
      srcSet={srcSet}
      sizes={sizes}
    />
  ) : null;
  const avifSource = (
    <source
      type="image/avif"
      srcSet={resolvedAvifSrcSet}
      sizes={sizes}
    />
  );

  return (
    <picture>
      {preferAvif ? avifSource : webpSource}
      {preferAvif ? webpSource : avifSource}
      <img
        src={src}
        alt={alt}
        width={width}
        height={height}
        loading={loading}
        fetchPriority={fetchPriority}
        decoding={decoding}
        className={className}
      />
    </picture>
  );
}
