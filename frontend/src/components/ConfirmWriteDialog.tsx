import { AlertTriangle, X } from "lucide-react";

type ConfirmWriteDialogProps = {
  open: boolean;
  title: string;
  details: string[];
  onCancel: () => void;
  onConfirm: () => void;
};

export function ConfirmWriteDialog({ open, title, details, onCancel, onConfirm }: ConfirmWriteDialogProps) {
  if (!open) return null;
  return (
    <div className="dialog-backdrop" role="presentation">
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-write-title">
        <button className="icon-button dialog__close" onClick={onCancel} aria-label="关闭">
          <X size={18} />
        </button>
        <div className="dialog__icon">
          <AlertTriangle size={22} />
        </div>
        <h2 id="confirm-write-title">{title}</h2>
        <ul>
          {details.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <div className="dialog__actions">
          <button className="button button--secondary" onClick={onCancel}>
            取消
          </button>
          <button className="button button--danger" onClick={onConfirm}>
            确认执行
          </button>
        </div>
      </div>
    </div>
  );
}
