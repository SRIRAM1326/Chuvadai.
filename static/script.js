(() => {
  "use strict";

  const body = document.body;
  const MAX_UPLOAD_MB = Number(body.dataset.maxUploadMb) || 20;
  const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
  const ALLOWED_EXTENSIONS = new Set(["pdf", "png", "jpg", "jpeg"]);
  const numberFormatter = new Intl.NumberFormat("en-IN");

  const $ = (id) => document.getElementById(id);

  const dropzone = $("dropzone");
  const dropzoneIdle = $("dropzoneIdle");
  const fileInput = $("fileInput");
  const fileCard = $("fileCard");
  const fileType = $("fileType");
  const fileName = $("fileName");
  const fileMeta = $("fileMeta");
  const removeFileBtn = $("removeFile");
  const sampleBtn = $("sampleBtn");
  const uploadError = $("uploadError");
  const extractBtn = $("extractBtn");
  const extractLabel = extractBtn.querySelector(".btn-label");
  const progressWrap = $("progressWrap");
  const progressLabel = $("progressLabel");
  const progressPct = $("progressPct");
  const progressBar = $("progressBar");
  const progressTrack = document.querySelector(".progress-track");
  const statusPill = $("statusPill");
  const engineStatus = $("engineStatus");

  const resultPanel = $("resultPanel");
  const resultEmpty = $("resultEmpty");
  const resultContent = $("resultContent");
  const engineBadge = $("engineBadge");
  const pageCount = $("pageCount");
  const wordCount = $("wordCount");
  const charCount = $("charCount");
  const extractedText = $("extractedText");
  const copyBtn = $("copyBtn");
  const clearBtn = $("clearBtn");
  const downloadBtn = $("downloadBtn");
  const warnings = $("warnings");
  const warningText = $("warningText");
  const toast = $("toast");

  let selectedFile = null;
  let isProcessing = false;
  let progressTimer = null;
  let progressValue = 0;
  let toastTimer = null;

  const delay = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

  function fileExtension(name) {
    const match = /\.([^.]+)$/.exec(name || "");
    return match ? match[1].toLowerCase() : "";
  }

  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return "0 KB";
    const units = ["B", "KB", "MB", "GB"];
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    const value = bytes / 1024 ** index;
    const digits = index === 0 || value >= 10 ? 0 : 1;
    return `${value.toFixed(digits)} ${units[index]}`;
  }

  function showToast(message, tone = "info") {
    window.clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.remove("is-success", "is-error");
    if (tone === "success") toast.classList.add("is-success");
    if (tone === "error") toast.classList.add("is-error");
    toast.classList.add("is-visible");
    toastTimer = window.setTimeout(() => {
      toast.classList.remove("is-visible");
    }, 3800);
  }

  function showUploadError(message) {
    uploadError.textContent = message;
    uploadError.hidden = false;
  }

  function clearUploadError() {
    uploadError.textContent = "";
    uploadError.hidden = true;
  }

  function setProgress(value, label) {
    progressValue = Math.max(0, Math.min(100, value));
    progressBar.style.width = `${progressValue}%`;
    progressPct.textContent = `${Math.round(progressValue)}%`;
    progressTrack.setAttribute("aria-valuenow", String(Math.round(progressValue)));
    if (label) progressLabel.textContent = label;
  }

  function stopProgressTimer() {
    if (progressTimer !== null) {
      window.clearInterval(progressTimer);
      progressTimer = null;
    }
  }

  function startProgressTimer() {
    stopProgressTimer();
    progressTimer = window.setInterval(() => {
      if (progressValue >= 88) return;
      const increment = Math.max(0.7, (90 - progressValue) * 0.07);
      const next = Math.min(88, progressValue + increment);
      const label =
        next < 58
          ? "Uploading document…"
          : "BharatOCR is reading your document…";
      setProgress(next, label);
    }, 680);
  }

  function updateStats() {
    const value = extractedText.value;
    const trimmed = value.trim();
    const words = trimmed ? (trimmed.match(/\S+/g) || []).length : 0;
    const lines = trimmed ? value.split("\n").length : 0;

    wordCount.textContent = `${numberFormatter.format(words)} ${words === 1 ? "word" : "words"}`;
    charCount.textContent =
      `${numberFormatter.format(value.length)} ${value.length === 1 ? "character" : "characters"}` +
      ` · ${numberFormatter.format(lines)} ${lines === 1 ? "line" : "lines"}`;

    const hasText = Boolean(trimmed);
    copyBtn.disabled = !hasText;
    downloadBtn.disabled = !hasText;
    clearBtn.disabled = !value;
  }

  function resetResult() {
    resultEmpty.hidden = false;
    resultContent.hidden = true;
    engineBadge.hidden = true;
    engineBadge.textContent = "";
    engineBadge.removeAttribute("title");
    warnings.hidden = true;
    warningText.textContent = "";
    extractedText.value = "";
    updateStats();
  }

  function setDropzoneLabel() {
    if (selectedFile) {
      dropzone.setAttribute(
        "aria-label",
        `Selected file ${selectedFile.name}. Press Enter to choose a different file.`
      );
    } else {
      dropzone.setAttribute(
        "aria-label",
        "Upload a document. Drag and drop, or press Enter to browse."
      );
    }
  }

  function setSelectedFile(file) {
    if (isProcessing) {
      showToast("Please wait for the current document to finish.", "info");
      return;
    }

    const extension = fileExtension(file.name);
    if (!ALLOWED_EXTENSIONS.has(extension)) {
      showUploadError("Please choose a PDF, JPG, JPEG, or PNG file.");
      showToast("That file type is not supported.", "error");
      return;
    }
    if (file.size === 0) {
      showUploadError("That file is empty. Please choose another document.");
      showToast("The selected file is empty.", "error");
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      showUploadError(`That file is ${formatBytes(file.size)}. The limit is ${MAX_UPLOAD_MB} MB.`);
      showToast("That file is too large.", "error");
      return;
    }

    selectedFile = file;
    clearUploadError();
    resetResult();

    fileType.textContent = extension === "jpeg" ? "JPG" : extension.toUpperCase();
    fileName.textContent = file.name;
    fileMeta.textContent = `${extension === "jpeg" ? "JPG" : extension.toUpperCase()} · ${formatBytes(file.size)}`;
    fileName.title = file.name;

    dropzoneIdle.hidden = true;
    fileCard.hidden = false;
    dropzone.classList.add("has-file");
    extractBtn.disabled = false;
    setDropzoneLabel();
    fileInput.value = "";
  }

  function clearSelectedFile(options = {}) {
    if (isProcessing) return;
    selectedFile = null;
    fileInput.value = "";
    dropzoneIdle.hidden = false;
    fileCard.hidden = true;
    dropzone.classList.remove("has-file");
    extractBtn.disabled = true;
    resetResult();
    clearUploadError();
    setDropzoneLabel();
    if (options.focus !== false) dropzone.focus();
  }

  function showResult(data) {
    const text = typeof data.text === "string" ? data.text : "";
    if (!text.trim()) {
      throw new Error("No readable text was returned. Try a clearer document.");
    }

    resultEmpty.hidden = true;
    resultContent.hidden = false;
    extractedText.value = text;

    const pages = Number(data.pages) || 1;
    pageCount.textContent = `${numberFormatter.format(pages)} ${pages === 1 ? "page" : "pages"}`;
    engineBadge.textContent = data.engine || "OCR complete";
    engineBadge.title = data.engine || "OCR complete";
    engineBadge.hidden = false;

    const warningList = Array.isArray(data.warnings) ? data.warnings.filter(Boolean) : [];
    if (warningList.length) {
      warningText.textContent = warningList.join(" ");
      warnings.hidden = false;
    } else {
      warningText.textContent = "";
      warnings.hidden = true;
    }

    updateStats();

    if (window.matchMedia("(max-width: 900px)").matches) {
      const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      resultPanel.scrollIntoView({
        behavior: reduceMotion ? "auto" : "smooth",
        block: "start",
      });
    }
  }

  async function loadStatus() {
    try {
      const response = await fetch("/api/status", {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Status unavailable");

      statusPill.classList.remove("is-cloud", "is-local", "is-issue");
      if (data.cloud_configured) {
        engineStatus.textContent = "BharatOCR Cloud connected";
        statusPill.classList.add("is-cloud");
        statusPill.title = "BharatOCR Cloud is configured and ready.";
      } else if (data.local_available) {
        engineStatus.textContent = `${data.local_engine || "Local OCR"} ready`;
        statusPill.classList.add("is-local");
        statusPill.title = "BharatOCR Cloud is not configured; local OCR will be used.";
      } else {
        engineStatus.textContent = "PDF text mode";
        statusPill.title =
          "No OCR engine is available for images. Digital PDFs with text still work.";
      }
    } catch (error) {
      statusPill.classList.remove("is-cloud", "is-local");
      statusPill.classList.add("is-issue");
      engineStatus.textContent = "OCR status unavailable";
      statusPill.title = error.message;
    }
  }

  function uploadFile(file) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const formData = new FormData();
      formData.append("file", file, file.name);

      xhr.open("POST", "/api/ocr");
      xhr.responseType = "json";
      xhr.timeout = 240000;
      xhr.setRequestHeader("Accept", "application/json");

      xhr.upload.addEventListener("loadstart", () => {
        setProgress(3, "Uploading document…");
      });

      xhr.upload.addEventListener("progress", (event) => {
        if (!event.lengthComputable) return;
        const percent = 5 + (event.loaded / event.total) * 52;
        setProgress(Math.min(57, percent), "Uploading document…");
      });

      xhr.upload.addEventListener("load", () => {
        setProgress(Math.max(progressValue, 62), "BharatOCR is reading your document…");
      });

      xhr.addEventListener("load", () => {
        let data = xhr.response;
        if (!data) {
          try {
            data = JSON.parse(xhr.responseText || "{}");
          } catch (_error) {
            data = {};
          }
        }

        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(data);
          return;
        }

        let message = data.error || "The document could not be processed.";
        if (xhr.status === 413) {
          message = `That file is too large. The maximum upload size is ${MAX_UPLOAD_MB} MB.`;
        } else if (xhr.status === 0) {
          message = "Could not reach the server. Is the Flask app still running?";
        }
        const error = new Error(message);
        error.status = xhr.status;
        reject(error);
      });

      xhr.addEventListener("error", () => {
        reject(new Error("Could not reach the server. Check your connection and try again."));
      });

      xhr.addEventListener("timeout", () => {
        reject(new Error("The OCR request timed out. Try a smaller document."));
      });

      xhr.addEventListener("abort", () => {
        reject(new Error("The upload was cancelled."));
      });

      xhr.send(formData);
    });
  }

  async function handleExtract() {
    if (!selectedFile || isProcessing) return;

    isProcessing = true;
    clearUploadError();
    extractBtn.disabled = true;
    extractBtn.classList.add("is-processing");
    extractLabel.textContent = "Extracting text…";
    removeFileBtn.disabled = true;
    sampleBtn.disabled = true;
    resultPanel.setAttribute("aria-busy", "true");
    progressWrap.hidden = false;
    setProgress(2, "Uploading document…");
    startProgressTimer();

    try {
      const data = await uploadFile(selectedFile);
      stopProgressTimer();
      setProgress(100, "Text extracted");
      await delay(260);
      showResult(data);
      showToast("Text extracted. You can edit it before downloading.", "success");
    } catch (error) {
      stopProgressTimer();
      showUploadError(error.message || "The document could not be processed.");
      showToast("Could not extract text from this document.", "error");
    } finally {
      progressWrap.hidden = true;
      resultPanel.removeAttribute("aria-busy");
      isProcessing = false;
      extractBtn.classList.remove("is-processing");
      extractLabel.textContent = "Extract text";
      extractBtn.disabled = !selectedFile;
      removeFileBtn.disabled = false;
      sampleBtn.disabled = false;
    }
  }

  async function copyExtractedText() {
    const text = extractedText.value;
    if (!text.trim()) return;

    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        throw new Error("Clipboard API unavailable");
      }
    } catch (_error) {
      extractedText.focus();
      extractedText.select();
      const copied = document.execCommand("copy");
      const selectionEnd = extractedText.value.length;
      extractedText.setSelectionRange(selectionEnd, selectionEnd);
      if (!copied) {
        showToast("Copy failed. Select the text and copy it manually.", "error");
        return;
      }
    }
    showToast("Extracted text copied to clipboard.", "success");
  }

  function downloadText() {
    const text = extractedText.value;
    if (!text.trim()) return;

    const originalName = selectedFile ? selectedFile.name : "extracted";
    const base = originalName
      .replace(/\.[^.]+$/, "")
      .replace(/[\\/:*?"<>|]+/g, "")
      .trim()
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 60) || "extracted";

    // A UTF-8 BOM keeps Indic text readable in older Windows text editors.
    const blob = new Blob(["\uFEFF", text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${base}-extracted.txt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1500);
    showToast("Text file downloaded.", "success");
  }

  function clearText() {
    if (!extractedText.value) return;
    const confirmed = window.confirm(
      "Clear all extracted text? You can extract the document again if needed."
    );
    if (!confirmed) return;
    extractedText.value = "";
    updateStats();
    extractedText.focus();
    showToast("Extracted text cleared.", "info");
  }

  async function loadSample() {
    if (isProcessing) return;
    sampleBtn.disabled = true;
    try {
      const response = await fetch("/static/sample-document.png", { cache: "no-store" });
      if (!response.ok) throw new Error("Sample document unavailable");
      const blob = await response.blob();
      const file = new File([blob], "sample-water-bill.png", {
        type: blob.type || "image/png",
      });
      setSelectedFile(file);
      showToast("Sample loaded. Press Extract text to try it.", "success");
    } catch (_error) {
      showUploadError("The sample document could not be loaded. Please upload your own file.");
      showToast("Could not load the sample document.", "error");
    } finally {
      sampleBtn.disabled = false;
    }
  }

  // File picker and drag/drop
  dropzone.addEventListener("click", (event) => {
    if (isProcessing) return;
    if (event.target.closest("button")) return;
    fileInput.click();
  });

  dropzone.addEventListener("keydown", (event) => {
    if (isProcessing) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", () => {
    const file = fileInput.files && fileInput.files[0];
    if (file) setSelectedFile(file);
  });

  removeFileBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    clearSelectedFile();
  });

  dropzone.addEventListener("dragenter", (event) => {
    if (isProcessing) return;
    event.preventDefault();
    dropzone.classList.add("is-dragging");
  });

  dropzone.addEventListener("dragover", (event) => {
    if (isProcessing) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    dropzone.classList.add("is-dragging");
  });

  dropzone.addEventListener("dragleave", (event) => {
    if (!dropzone.contains(event.relatedTarget)) {
      dropzone.classList.remove("is-dragging");
    }
  });

  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-dragging");
    if (isProcessing) return;
    const files = event.dataTransfer.files;
    if (!files || !files.length) return;
    if (files.length > 1) {
      showToast("Only the first document will be used.", "info");
    }
    setSelectedFile(files[0]);
  });

  ["dragover", "drop"].forEach((eventName) => {
    window.addEventListener(eventName, (event) => {
      if (event.dataTransfer && Array.from(event.dataTransfer.types).includes("Files")) {
        event.preventDefault();
      }
    });
  });

  extractBtn.addEventListener("click", handleExtract);
  sampleBtn.addEventListener("click", loadSample);
  copyBtn.addEventListener("click", copyExtractedText);
  downloadBtn.addEventListener("click", downloadText);
  clearBtn.addEventListener("click", clearText);
  extractedText.addEventListener("input", updateStats);

  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      if (selectedFile && !isProcessing) {
        event.preventDefault();
        handleExtract();
      }
    }
  });

  resetResult();
  setDropzoneLabel();
  updateStats();
  loadStatus();
})();
