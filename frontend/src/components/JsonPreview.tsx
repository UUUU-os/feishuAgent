type JsonPreviewProps = {
  value: unknown;
  maxHeight?: number;
};

export function JsonPreview({ value, maxHeight = 260 }: JsonPreviewProps) {
  return (
    <pre className="json-preview" style={{ maxHeight }}>
      {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
    </pre>
  );
}
