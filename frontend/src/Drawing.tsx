import { useEffect, useRef, useState, type PointerEvent } from "react";

export function Drawing({
  value,
  onChange,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const painting = useRef(false);
  const history = useRef<string[]>([]);
  const [color, setColor] = useState("#30233f");
  const [width, setWidth] = useState(4);
  const [hasHistory, setHasHistory] = useState(false);
  const [restoring, setRestoring] = useState(Boolean(value));
  const context = () => canvas.current!.getContext("2d")!;
  useEffect(() => {
    const element = canvas.current!;
    const ctx = element.getContext("2d")!;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, element.width, element.height);
    if (value) {
      const image = new Image();
      image.onload = () => {
        ctx.drawImage(image, 0, 0);
        setRestoring(false);
      };
      image.onerror = () => setRestoring(false);
      image.src = value;
      return () => {
        image.onload = null;
        image.onerror = null;
      };
    }
  }, []);
  const point = (event: PointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      ((event.clientX - rect.left) * event.currentTarget.width) / rect.width,
      ((event.clientY - rect.top) * event.currentTarget.height) / rect.height,
    ] as const;
  };
  const begin = (event: PointerEvent<HTMLCanvasElement>) => {
    if (event.button !== 0 || restoring) return;
    event.preventDefault();
    history.current.push(value);
    if (history.current.length > 20) history.current.shift();
    setHasHistory(true);
    event.currentTarget.setPointerCapture(event.pointerId);
    painting.current = true;
    const ctx = context();
    const [x, y] = point(event);
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = width;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.arc(x, y, width / 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(x, y);
  };
  const move = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!painting.current) return;
    const [x, y] = point(event);
    const ctx = context();
    ctx.lineTo(x, y);
    ctx.stroke();
  };
  const finish = () => {
    if (painting.current) {
      painting.current = false;
      onChange(canvas.current!.toDataURL("image/png"));
    }
  };
  const restore = (imageValue: string) => {
    const ctx = context();
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, 800, 500);
    if (imageValue) {
      setRestoring(true);
      const image = new Image();
      image.onload = () => {
        ctx.drawImage(image, 0, 0);
        setRestoring(false);
      };
      image.onerror = () => setRestoring(false);
      image.src = imageValue;
    }
    onChange(imageValue);
  };
  return (
    <div className="drawing">
      <div className="drawing-toolbar">
        <label>
          笔色
          <input
            type="color"
            value={color}
            onChange={(event) => setColor(event.target.value)}
          />
        </label>
        <label>
          笔宽
          <select
            value={width}
            onChange={(event) => setWidth(Number(event.target.value))}
          >
            <option value={2}>细</option>
            <option value={4}>中</option>
            <option value={10}>粗</option>
            <option value={24}>宽</option>
          </select>
        </label>
        <button
          type="button"
          className="quiet"
          disabled={!hasHistory || restoring}
          onClick={() => {
            const previous = history.current.pop();
            if (previous !== undefined) restore(previous);
            setHasHistory(history.current.length > 0);
          }}
        >
          撤销
        </button>
        <button
          type="button"
          className="quiet"
          disabled={restoring}
          onClick={() => {
            history.current.push(value);
            setHasHistory(true);
            restore("");
          }}
        >
          清空
        </button>
      </div>
      <canvas
        ref={canvas}
        width={800}
        height={500}
        onPointerDown={begin}
        onPointerMove={move}
        onPointerUp={finish}
        onPointerCancel={finish}
        aria-label={`${label}画板，使用手指或鼠标绘画`}
        aria-busy={restoring}
      />
      <p className="hint">
        {restoring
          ? "正在恢复画作…"
          : "画作是本机私密草稿；确认提交后才发送给服务器。可手绘，或导入自己准备的图片。"}
      </p>
      <label className="file-field">
        导入画作
        <input
          type="file"
          accept="image/png,image/jpeg"
          disabled={restoring}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            if (file.size > 5 * 1024 * 1024) {
              event.target.setCustomValidity("图片不能超过5MB");
              event.target.reportValidity();
              return;
            }
            event.target.setCustomValidity("");
            setRestoring(true);
            const url = URL.createObjectURL(file);
            const image = new Image();
            image.onload = () => {
              if (!canvas.current) {
                URL.revokeObjectURL(url);
                return;
              }
              history.current.push(value);
              setHasHistory(true);
              const ctx = context();
              ctx.fillStyle = "#ffffff";
              ctx.fillRect(0, 0, 800, 500);
              const scale = Math.min(800 / image.width, 500 / image.height);
              ctx.drawImage(
                image,
                (800 - image.width * scale) / 2,
                (500 - image.height * scale) / 2,
                image.width * scale,
                image.height * scale,
              );
              onChange(canvas.current!.toDataURL("image/png"));
              setRestoring(false);
              URL.revokeObjectURL(url);
            };
            image.onerror = () => {
              setRestoring(false);
              URL.revokeObjectURL(url);
              event.target.setCustomValidity("无法读取此图片，请选择PNG或JPEG");
              event.target.reportValidity();
            };
            image.src = url;
          }}
        />
      </label>
    </div>
  );
}
