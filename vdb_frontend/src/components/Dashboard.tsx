"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  Upload,
  Play,
  CheckCircle,
  XCircle,
  Download,
  AlertCircle,
  Trash2,
  History,
  Sparkles,
  LogOut,
  FileText,
  Loader2,
  Settings,
  ExternalLink,
  Link2,
  Unlink,
} from "lucide-react";
import { apiFetch, clearStoredToken } from "@/utils/api";
import styles from "./Dashboard.module.css";

interface DashboardProps {
  username: string;
  onLogout: () => void;
}

interface ScrapperJob {
  id: string;
  original_filename: string;
  status: "pending" | "running" | "completed" | "failed";
  error_message: string;
  created_at: string;
  google_drive_file_id?: string;
}

export default function Dashboard({ username, onLogout }: DashboardProps) {
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [notification, setNotification] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  // Scraper controls
  const [activeJob, setActiveJob] = useState<ScrapperJob | null>(null);
  const [dryRun, setDryRun] = useState(false);
  const [runningScraper, setRunningScraper] = useState(false);

  // History list
  const [jobs, setJobs] = useState<ScrapperJob[]>([]);
  const [downloadingJobId, setDownloadingJobId] = useState<string | null>(null);

  // Settings modal controls
  const [showSettings, setShowSettings] = useState(false);
  const [curlCommand, setCurlCommand] = useState("");
  const [updatingSettings, setUpdatingSettings] = useState(false);
  const [settingsNotification, setSettingsNotification] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  // Google Drive connection state
  const [gdriveConnected, setGdriveConnected] = useState(false);
  const [gdriveFolderId, setGdriveFolderId] = useState("");
  const [gdriveLoading, setGdriveLoading] = useState(false);

  // Ref to file input element
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Read job history from localStorage on mount
  useEffect(() => {
    const storedJobs = localStorage.getItem("vdb_jobs");
    if (storedJobs) {
      try {
        setJobs(JSON.parse(storedJobs));
      } catch (e) {
        console.error("Failed to parse stored jobs", e);
      }
    }
  }, []);

  // Save job history to localStorage when changed
  const saveJobs = (updatedJobs: ScrapperJob[]) => {
    setJobs(updatedJobs);
    localStorage.setItem("vdb_jobs", JSON.stringify(updatedJobs));
  };

  // Fetch Google Drive config on mount & handle OAuth callback URL params
  useEffect(() => {
    // Check if returning from Google OAuth
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (params.get("gdrive_connected") === "1") {
        setNotification({
          type: "success",
          message: "Google Drive connected successfully! You can now upload files.",
        });
        // Clean up URL params
        window.history.replaceState({}, "", window.location.pathname);
      }
      if (params.get("gdrive_error")) {
        setNotification({
          type: "error",
          message: `Google Drive authorization failed: ${params.get("gdrive_error")}`,
        });
        window.history.replaceState({}, "", window.location.pathname);
      }
    }

    // Fetch current GDrive config
    const fetchGdriveConfig = async () => {
      try {
        const response = await apiFetch("/scrapper/gdrive-config", {
          method: "GET",
        });
        const data = await response.json();
        setGdriveConnected(data.is_connected);
        setGdriveFolderId(data.folder_id || "");
      } catch (err) {
        console.error("Failed to fetch GDrive config:", err);
      }
    };
    fetchGdriveConfig();
  }, []);

  // Logout handler
  const handleLogoutClick = async () => {
    try {
      // Call optional logout endpoint to revoke token in DB
      await apiFetch("/auth/logout", { method: "POST" });
    } catch (e) {
      console.warn("Logout request failed, proceeding to clear client session", e);
    } finally {
      clearStoredToken();
      onLogout();
    }
  };

  // Session configuration handler
  const handleUpdateSession = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!curlCommand.trim()) return;

    setUpdatingSettings(true);
    setSettingsNotification(null);

    try {
      const response = await apiFetch("/auth/session-curl", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ curl_command: curlCommand }),
      });

      const data = await response.json();
      setSettingsNotification({
        type: "success",
        message: data.detail || "Session configuration updated successfully!",
      });
      setCurlCommand("");

      // Auto close modal after 1.5 seconds on success
      setTimeout(() => {
        setShowSettings(false);
        setSettingsNotification(null);
      }, 1500);

    } catch (err: any) {
      console.error("Session update error:", err);
      setSettingsNotification({
        type: "error",
        message: err.message || "Failed to parse and update session. Please check your cURL syntax.",
      });
    } finally {
      setUpdatingSettings(false);
    }
  };

  // Drag & Drop event handlers
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  const validateAndSetFile = (selectedFile: File) => {
    setNotification(null);
    const ext = selectedFile.name.split(".").pop()?.toLowerCase();
    if (ext !== "xlsx") {
      setNotification({
        type: "error",
        message: "Only Microsoft Excel (.xlsx) files are allowed.",
      });
      return;
    }

    if (selectedFile.size > 10 * 1024 * 1024) {
      setNotification({
        type: "error",
        message: "File is too large. Maximum size is 10 MB.",
      });
      return;
    }

    setFile(selectedFile);
  };

  const removeFile = () => {
    setFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  // File upload logic
  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;

    setUploading(true);
    setNotification(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await apiFetch("/scrapper/upload", {
        method: "POST",
        body: formData,
        // Fetch will set the correct content-type header with boundary automatically for FormData
      });

      const data = await response.json();
      
      const newJob: ScrapperJob = {
        id: data.id,
        original_filename: data.original_filename,
        status: data.status,
        error_message: data.error_message || "",
        created_at: new Date().toLocaleString(),
        google_drive_file_id: data.google_drive_file_id,
      };

      // Set as active job and add to history
      setActiveJob(newJob);
      saveJobs([newJob, ...jobs]);
      setNotification({
        type: "success",
        message: `File uploaded successfully! Job ID: ${data.id}`,
      });
      removeFile();
    } catch (err: any) {
      console.error("Upload error:", err);

      // Handle 403: Google Drive not authorized
      if (err.message && err.message.includes("gdrive_auth_required")) {
        // Redirect user to Google Drive OAuth
        try {
          const authResponse = await apiFetch("/auth/gdrive/authorize", {
            method: "GET",
          });
          const authData = await authResponse.json();
          if (authData.auth_url) {
            window.location.href = authData.auth_url;
            return;
          }
        } catch (authErr: any) {
          console.error("Failed to get auth URL:", authErr);
        }
        setNotification({
          type: "error",
          message: "Google Drive is not connected. Please connect it via Settings first.",
        });
      } else {
        setNotification({
          type: "error",
          message: err.message || "Failed to upload file. Please try again.",
        });
      }
    } finally {
      setUploading(false);
    }
  };

  // Run scraper logic
  // Trigger or resume scraper execution for a specific job
  const handleRunJob = async (job: ScrapperJob) => {
    setRunningScraper(true);
    setNotification(null);

    try {
      const response = await apiFetch(
        `/scrapper/run/${job.id}?dry_run=${dryRun}`,
        { method: "POST" }
      );
      const data = await response.json();

      // Update state for activeJob and history list
      const updatedJob: ScrapperJob = {
        ...job,
        status: data.status,
        error_message: "", // Clear error message on retry
        google_drive_file_id: data.google_drive_file_id || job.google_drive_file_id,
      };
      
      setActiveJob(updatedJob);
      updateJobInHistory(updatedJob);

      setNotification({
        type: "success",
        message: `Scraper started/resumed successfully. Status: ${data.status}.`,
      });
    } catch (err: any) {
      console.error("Scraper execution error:", err);
      setNotification({
        type: "error",
        message: err.message || "Failed to execute scraper. Please try again.",
      });
    } finally {
      setRunningScraper(false);
    }
  };

  const handleRunScraper = () => {
    if (activeJob) {
      handleRunJob(activeJob);
    }
  };

  const handleStartNewUpload = () => {
    setActiveJob(null);
    setFile(null);
    setNotification(null);
  };

  // Helper: Update a single job's data in the history list
  const updateJobInHistory = useCallback((updatedJob: ScrapperJob) => {
    setJobs((prevJobs) => {
      const newJobs = prevJobs.map((j) => (j.id === updatedJob.id ? updatedJob : j));
      localStorage.setItem("vdb_jobs", JSON.stringify(newJobs));
      return newJobs;
    });
  }, []);

  // Poll status helper
  const checkActiveJobs = useCallback(async () => {
    const activeJobs = jobs.filter(
      (j) => j.status === "pending" || j.status === "running"
    );

    if (activeJobs.length === 0) return;

    for (const job of activeJobs) {
      try {
        const response = await apiFetch(`/scrapper/status/${job.id}`, {
          method: "GET",
        });
        const data = await response.json();

        if (data.status !== job.status || data.error_message !== job.error_message) {
          const updated: ScrapperJob = {
            ...job,
            status: data.status,
            error_message: data.error_message || "",
            google_drive_file_id: data.google_drive_file_id || job.google_drive_file_id,
          };

          // Update history
          updateJobInHistory(updated);

          // If this is the currently focused active job, update it too
          if (activeJob && activeJob.id === job.id) {
            setActiveJob(updated);
          }
        }
      } catch (err) {
        console.error(`Error polling status for job ${job.id}:`, err);
      }
    }
  }, [jobs, activeJob, updateJobInHistory]);

  // Set up polling effect every 4 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      checkActiveJobs();
    }, 4000);

    return () => clearInterval(interval);
  }, [checkActiveJobs]);

  // Download logic (Blob-based to ensure Authorization headers are sent)
  const handleDownload = async (job: ScrapperJob) => {
    setDownloadingJobId(job.id);
    try {
      const response = await apiFetch(`/scrapper/download/${job.id}`, {
        method: "GET",
      });

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `enriched_${job.original_filename}`;
      document.body.appendChild(a);
      a.click();
      
      // Cleanup
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: any) {
      console.error("Download error:", err);
      alert(err.message || "Failed to download result file.");
    } finally {
      setDownloadingJobId(null);
    }
  };

  const clearHistory = async () => {
    if (
      confirm(
        "Are you sure you want to clear history? This will stop all active scraper jobs, delete all job records from the server, and wipe all uploaded files."
      )
    ) {
      try {
        setNotification(null);
        await apiFetch("/scrapper/flush", {
          method: "POST",
        });
        setJobs([]);
        localStorage.removeItem("vdb_jobs");
        setActiveJob(null);
        setNotification({
          type: "success",
          message: "All server data flushed and history cleared successfully.",
        });
      } catch (err: any) {
        console.error("Flush error:", err);
        setNotification({
          type: "error",
          message: err.message || "Failed to flush server data.",
        });
      }
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "pending":
        return (
          <span className={`${styles.badge} ${styles.badgePending}`}>
            Pending
          </span>
        );
      case "running":
        return (
          <span className={`${styles.badge} ${styles.badgeRunning}`}>
            <span className={styles.badgeSpinner} />
            Running
          </span>
        );
      case "completed":
        return (
          <span className={`${styles.badge} ${styles.badgeCompleted}`}>
            Completed
          </span>
        );
      case "failed":
        return (
          <span className={`${styles.badge} ${styles.badgeFailed}`}>
            Failed
          </span>
        );
      default:
        return <span className={styles.badge}>{status}</span>;
    }
  };

  return (
    <div className={styles.dashboard}>
      {/* Navbar Header */}
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <Sparkles className={styles.logoIcon} />
          <span className={styles.logoText}>VDB2 Scrapper Panel</span>
        </div>
        <div className={styles.headerRight}>
          <div className={styles.userInfo}>
            <div className={styles.userAvatar}>
              {username.charAt(0).toUpperCase()}
            </div>
            <span>{username}</span>
          </div>
          <button
            className={styles.settingsBtn}
            onClick={() => {
              setShowSettings(true);
              setSettingsNotification(null);
            }}
          >
            <Settings size={16} />
            <span>Session Config</span>
          </button>
          <button className={styles.logoutBtn} onClick={handleLogoutClick}>
            <LogOut size={16} />
            <span>Logout</span>
          </button>
        </div>
      </header>

      {/* Main Workspace Layout */}
      <main className={styles.main}>
        <div className={styles.grid}>
          
          {/* Left Hand: Upload & Controls */}
          <div className={styles.panel}>
            <h2 className={styles.panelTitle}>
              <Upload size={20} />
              <span>Import Criteria Sheet</span>
            </h2>

            {notification && (
              <div
                className={`${styles.alert} ${
                  notification.type === "error"
                    ? styles.alertDanger
                    : styles.alertSuccess
                }`}
              >
                <AlertCircle size={20} className={styles.alertIcon} />
                <span>{notification.message}</span>
              </div>
            )}

            {!activeJob ? (
              <form onSubmit={handleUpload}>
                <div
                  className={`${styles.dropzone} ${
                    dragActive ? styles.dropzoneActive : ""
                  }`}
                  onDragEnter={handleDrag}
                  onDragOver={handleDrag}
                  onDragLeave={handleDrag}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    className={styles.fileInput}
                    accept=".xlsx"
                    onChange={handleFileChange}
                    disabled={uploading}
                  />
                  <Upload className={styles.uploadIcon} />
                  <p className={styles.uploadTextPrimary}>
                    Drag and drop file here, or click to browse
                  </p>
                  <p className={styles.uploadTextSecondary}>
                    Supported formats: .xlsx (Max 10MB)
                  </p>
                </div>

                {file && (
                  <div className={styles.fileCard}>
                    <FileText className={styles.fileIcon} size={24} />
                    <div className={styles.fileDetails}>
                      <div className={styles.fileName}>{file.name}</div>
                      <div className={styles.fileSize}>
                        {(file.size / 1024).toFixed(1)} KB
                      </div>
                    </div>
                    <button
                      type="button"
                      className={styles.removeFileBtn}
                      onClick={(e) => {
                        e.stopPropagation();
                        removeFile();
                      }}
                      disabled={uploading}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                )}

                <button
                  type="submit"
                  className={styles.uploadBtn}
                  disabled={!file || uploading}
                >
                  {uploading ? (
                    <>
                      <Loader2 className={styles.spinner} size={18} />
                      <span>Uploading File...</span>
                    </>
                  ) : (
                    <span>Upload Excel File</span>
                  )}
                </button>
              </form>
            ) : (
              // Active Job configuration panel
              <div className={styles.actionGroup}>
                <div className={styles.fileCard}>
                  <FileText className={styles.fileIcon} size={24} />
                  <div className={styles.fileDetails}>
                    <div className={styles.fileName}>
                      {activeJob.original_filename}
                    </div>
                    <div className={styles.fileSize}>
                      ID: {activeJob.id.substring(0, 8)}...
                    </div>
                  </div>
                  <div>{getStatusBadge(activeJob.status)}</div>
                </div>

                {activeJob.status === "pending" && (
                  <>
                    <div className={styles.toggleContainer}>
                      <div className={styles.toggleLabelBlock}>
                        <span className={styles.toggleLabel}>Dry Run Execution</span>
                        <span className={styles.toggleDesc}>
                          Runs using mock database cache, preventing live search requests.
                        </span>
                      </div>
                      <label className={styles.switch}>
                        <input
                          type="checkbox"
                          checked={dryRun}
                          onChange={(e) => setDryRun(e.target.checked)}
                          disabled={runningScraper}
                        />
                        <span className={styles.slider}></span>
                      </label>
                    </div>

                    <button
                      className={styles.runBtn}
                      onClick={handleRunScraper}
                      disabled={runningScraper}
                    >
                      {runningScraper ? (
                        <>
                          <Loader2 className={styles.spinner} size={18} />
                          <span>Initiating...</span>
                        </>
                      ) : (
                        <>
                          <Play size={18} />
                          <span>Start VDB Scraper</span>
                        </>
                      )}
                    </button>
                  </>
                )}

                {activeJob.status === "running" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                    <div className={styles.alert} style={{ background: "rgba(99, 102, 241, 0.08)", border: "1px solid rgba(99, 102, 241, 0.2)", color: "#a5b4fc", margin: 0 }}>
                      <Loader2 className={styles.spinner} style={{ marginRight: 8, animationDuration: "1.2s" }} />
                      <div>
                        <strong>Scraper In Progress:</strong> The backend is executing searches. Check the progress log on the right.
                      </div>
                    </div>
                    {activeJob.google_drive_file_id && (
                      <a
                        href={`https://docs.google.com/spreadsheets/d/${activeJob.google_drive_file_id}/edit`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={styles.driveLink}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          gap: "8px",
                          padding: "12px 16px",
                          borderRadius: "8px",
                          fontSize: "14px",
                          fontWeight: 600,
                          background: "rgba(34, 197, 94, 0.08)",
                          border: "1px solid rgba(34, 197, 94, 0.2)",
                          color: "#86efac",
                          textDecoration: "none",
                          transition: "all 0.2s ease"
                        }}
                      >
                        <Sparkles size={18} />
                        <span>View Live in Sheets</span>
                      </a>
                    )}
                  </div>
                )}

                {activeJob.status === "completed" && (
                  <>
                    <div className={`${styles.alert} ${styles.alertSuccess}`}>
                      <CheckCircle className={styles.alertIcon} size={20} />
                      <div>
                        <strong>Scrape Completed!</strong> Enriched spreadsheet is ready for download.
                      </div>
                    </div>
                    
                    <div style={{ display: "flex", gap: "10px", width: "100%" }}>
                      <button
                        className={styles.runBtn}
                        onClick={() => handleDownload(activeJob)}
                        disabled={downloadingJobId === activeJob.id}
                        style={{ flex: 1, margin: 0 }}
                      >
                        {downloadingJobId === activeJob.id ? (
                          <>
                            <Loader2 className={styles.spinner} size={18} />
                            <span>Downloading...</span>
                          </>
                        ) : (
                          <>
                            <Download size={18} />
                            <span>Download Excel</span>
                          </>
                        )}
                      </button>

                      {activeJob.google_drive_file_id && (
                        <a
                          href={`https://docs.google.com/spreadsheets/d/${activeJob.google_drive_file_id}/edit`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={styles.driveLink}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            gap: "8px",
                            padding: "10px 16px",
                            borderRadius: "8px",
                            fontSize: "14px",
                            fontWeight: 600,
                            background: "rgba(34, 197, 94, 0.08)",
                            border: "1px solid rgba(34, 197, 94, 0.2)",
                            color: "#86efac",
                            textDecoration: "none",
                            transition: "all 0.2s ease",
                            flex: 1
                          }}
                        >
                          <Sparkles size={18} />
                          <span>View in Sheets</span>
                        </a>
                      )}
                    </div>

                    <button className={styles.resetBtn} onClick={handleStartNewUpload}>
                      Upload New File
                    </button>
                  </>
                )}

                {activeJob.status === "failed" && (
                  <>
                    <div className={styles.jobError} style={{ marginBottom: 20 }}>
                      <strong>Error Details:</strong> {activeJob.error_message || "Operation failed."}
                    </div>

                    <div className={styles.toggleContainer}>
                      <div className={styles.toggleLabelBlock}>
                        <span className={styles.toggleLabel}>Dry Run Execution</span>
                        <span className={styles.toggleDesc}>
                          Runs using mock database cache, preventing live search requests.
                        </span>
                      </div>
                      <label className={styles.switch}>
                        <input
                          type="checkbox"
                          checked={dryRun}
                          onChange={(e) => setDryRun(e.target.checked)}
                          disabled={runningScraper}
                        />
                        <span className={styles.slider}></span>
                      </label>
                    </div>

                    <div style={{ display: "flex", gap: "10px", width: "100%" }}>
                      <button
                        className={styles.runBtn}
                        onClick={handleRunScraper}
                        disabled={runningScraper}
                        style={{ flex: 1, margin: 0 }}
                      >
                        {runningScraper ? (
                          <>
                            <Loader2 className={styles.spinner} size={18} />
                            <span>Resuming...</span>
                          </>
                        ) : (
                          <>
                            <Play size={18} />
                            <span>Resume Scraper</span>
                          </>
                        )}
                      </button>

                      {activeJob.google_drive_file_id && (
                        <a
                          href={`https://docs.google.com/spreadsheets/d/${activeJob.google_drive_file_id}/edit`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={styles.driveLink}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            gap: "8px",
                            padding: "10px 16px",
                            borderRadius: "8px",
                            fontSize: "14px",
                            fontWeight: 600,
                            background: "rgba(34, 197, 94, 0.08)",
                            border: "1px solid rgba(34, 197, 94, 0.2)",
                            color: "#86efac",
                            textDecoration: "none",
                            transition: "all 0.2s ease",
                            flex: 1
                          }}
                        >
                          <Sparkles size={18} />
                          <span>View in Sheets</span>
                        </a>
                      )}
                    </div>

                    <button className={styles.resetBtn} onClick={handleStartNewUpload}>
                      Upload New File
                    </button>
                  </>
                )}
              </div>
            )}
          </div>

          {/* Right Hand: Job History list */}
          <div className={styles.panel}>
            <div className={styles.historyHeader}>
              <h2 className={styles.panelTitle} style={{ margin: 0 }}>
                <History size={20} />
                <span>Recent Operations</span>
              </h2>
              {jobs.length > 0 && (
                <button className={styles.clearBtn} onClick={clearHistory}>
                  Clear History
                </button>
              )}
            </div>

            <div className={styles.jobList}>
              {jobs.length === 0 ? (
                <div className={styles.emptyState}>
                  <History className={styles.emptyStateIcon} />
                  <p>No operations performed yet.</p>
                  <p style={{ fontSize: "12px", marginTop: "4px" }}>
                    Upload an Excel file to get started.
                  </p>
                </div>
              ) : (
                jobs.map((job) => (
                  <div className={styles.jobCard} key={job.id}>
                    <div className={styles.jobHeader}>
                      <div className={styles.jobMeta}>
                        <div className={styles.jobFilename} title={job.original_filename}>
                          {job.original_filename}
                        </div>
                        <div className={styles.jobTime}>
                          Uploaded: {job.created_at}
                        </div>
                      </div>
                      <div>{getStatusBadge(job.status)}</div>
                    </div>

                    {job.status === "failed" && job.error_message && (
                      <div className={styles.jobError}>
                        <strong>Error Details:</strong> {job.error_message}
                      </div>
                    )}

                    <div style={{ display: "flex", gap: "8px", marginTop: "8px", flexWrap: "wrap" }}>
                      {(job.status === "completed" || job.status === "failed") && (
                        <button
                          className={styles.downloadLink}
                          onClick={() => handleDownload(job)}
                          disabled={downloadingJobId === job.id}
                          style={job.status === "failed" ? { background: "rgba(239, 68, 68, 0.08)", border: "1px solid rgba(239, 68, 68, 0.2)", color: "#fca5a5" } : undefined}
                        >
                          {downloadingJobId === job.id ? (
                            <>
                              <div className={styles.downloadSpinner} />
                              <span>Downloading...</span>
                            </>
                          ) : (
                            <>
                              <Download size={14} />
                              <span>{job.status === "failed" ? "Download Partial Excel" : "Download Enriched Excel"}</span>
                            </>
                          )}
                        </button>
                      )}

                      {job.status === "failed" && (
                        <button
                          className={styles.resumeLink}
                          onClick={() => handleRunJob(job)}
                          disabled={runningScraper}
                        >
                          <Play size={14} />
                          <span>Resume</span>
                        </button>
                      )}

                      {job.google_drive_file_id && (
                        <a
                          href={`https://docs.google.com/spreadsheets/d/${job.google_drive_file_id}/edit`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={styles.driveLink}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "6px",
                            padding: "6px 12px",
                            borderRadius: "6px",
                            fontSize: "12px",
                            fontWeight: 500,
                            background: "rgba(34, 197, 94, 0.08)",
                            border: "1px solid rgba(34, 197, 94, 0.2)",
                            color: "#86efac",
                            textDecoration: "none",
                            transition: "all 0.2s ease"
                          }}
                        >
                          <Sparkles size={14} />
                          <span>View in Sheets</span>
                        </a>
                      )}
                    </div>

                    {(job.status === "pending" || job.status === "running") && (
                      <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "4px" }}>
                        <div style={{ display: "flex", gap: "8px", fontSize: "12px", color: "var(--text-muted)", alignItems: "center" }}>
                          <Loader2 className={styles.spinner} style={{ width: 12, height: 12 }} />
                          <span>Background processing active...</span>
                        </div>
                        {job.google_drive_file_id && (
                          <a
                            href={`https://docs.google.com/spreadsheets/d/${job.google_drive_file_id}/edit`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={styles.driveLink}
                            style={{
                              display: "inline-flex",
                              alignSelf: "flex-start",
                              alignItems: "center",
                              gap: "6px",
                              padding: "6px 12px",
                              borderRadius: "6px",
                              fontSize: "12px",
                              fontWeight: 500,
                              background: "rgba(34, 197, 94, 0.08)",
                              border: "1px solid rgba(34, 197, 94, 0.2)",
                              color: "#86efac",
                              textDecoration: "none",
                              transition: "all 0.2s ease"
                            }}
                          >
                            <Sparkles size={14} />
                            <span>View Live in Sheets</span>
                          </a>
                        )}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>

        </div>
      </main>

      {showSettings && (
        <div className={styles.modalOverlay} onClick={() => setShowSettings(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <h3 className={styles.modalTitle}>
              <Settings className={styles.logoIcon} style={{ marginRight: 8 }} />
              Settings
            </h3>

            {settingsNotification && (
              <div
                className={`${styles.alert} ${
                  settingsNotification.type === "error"
                    ? styles.alertDanger
                    : styles.alertSuccess
                }`}
                style={{ marginBottom: 16 }}
              >
                <AlertCircle size={20} className={styles.alertIcon} />
                <span>{settingsNotification.message}</span>
              </div>
            )}

            {/* ── Google Drive Section ── */}
            <div style={{
              padding: "16px",
              borderRadius: "10px",
              background: "rgba(255,255,255,0.03)",
              border: "1px solid var(--glass-border)",
              marginBottom: "20px"
            }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <Sparkles size={18} style={{ color: gdriveConnected ? "#4ade80" : "#94a3b8" }} />
                  <strong style={{ fontSize: "14px" }}>Google Drive</strong>
                </div>
                <span style={{
                  fontSize: "12px",
                  fontWeight: 600,
                  padding: "4px 10px",
                  borderRadius: "20px",
                  background: gdriveConnected ? "rgba(34, 197, 94, 0.1)" : "rgba(239, 68, 68, 0.1)",
                  color: gdriveConnected ? "#4ade80" : "#f87171",
                  border: `1px solid ${gdriveConnected ? "rgba(34, 197, 94, 0.2)" : "rgba(239, 68, 68, 0.2)"}`,
                }}>
                  {gdriveConnected ? "✓ Connected" : "✗ Not Connected"}
                </span>
              </div>

              {gdriveConnected ? (
                <>
                  <div style={{ marginBottom: "12px" }}>
                    <label style={{ display: "block", fontSize: "12px", color: "var(--text-muted)", marginBottom: "6px" }}>
                      Drive Folder ID
                    </label>
                    <div style={{ display: "flex", gap: "8px" }}>
                      <input
                        type="text"
                        value={gdriveFolderId}
                        onChange={(e) => setGdriveFolderId(e.target.value)}
                        placeholder="Enter your Google Drive folder ID"
                        style={{
                          flex: 1,
                          padding: "8px 12px",
                          borderRadius: "6px",
                          background: "rgba(255,255,255,0.04)",
                          border: "1px solid var(--glass-border)",
                          color: "var(--text-primary)",
                          fontSize: "13px",
                          outline: "none",
                        }}
                      />
                      <button
                        type="button"
                        onClick={async () => {
                          try {
                            await apiFetch("/scrapper/gdrive-config", {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ folder_id: gdriveFolderId }),
                            });
                            setSettingsNotification({ type: "success", message: "Folder ID saved!" });
                            setTimeout(() => setSettingsNotification(null), 2000);
                          } catch (err: any) {
                            setSettingsNotification({ type: "error", message: err.message || "Failed to save folder ID." });
                          }
                        }}
                        style={{
                          padding: "8px 16px",
                          borderRadius: "6px",
                          background: "rgba(99, 102, 241, 0.15)",
                          border: "1px solid rgba(99, 102, 241, 0.3)",
                          color: "#a5b4fc",
                          fontSize: "13px",
                          fontWeight: 600,
                          cursor: "pointer",
                        }}
                      >
                        Save
                      </button>
                    </div>
                    <p style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "6px" }}>
                      Find this in your Google Drive folder URL: drive.google.com/drive/folders/<strong>[THIS_IS_THE_ID]</strong>
                    </p>
                  </div>

                  <button
                    type="button"
                    onClick={async () => {
                      if (!confirm("Disconnect Google Drive? You will need to re-authorize to upload files.")) return;
                      setGdriveLoading(true);
                      try {
                        await apiFetch("/scrapper/gdrive-disconnect", { method: "POST" });
                        setGdriveConnected(false);
                        setGdriveFolderId("");
                        setSettingsNotification({ type: "success", message: "Google Drive disconnected." });
                      } catch (err: any) {
                        setSettingsNotification({ type: "error", message: err.message || "Failed to disconnect." });
                      } finally {
                        setGdriveLoading(false);
                      }
                    }}
                    disabled={gdriveLoading}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      padding: "8px 14px",
                      borderRadius: "6px",
                      background: "rgba(239, 68, 68, 0.08)",
                      border: "1px solid rgba(239, 68, 68, 0.2)",
                      color: "#fca5a5",
                      fontSize: "12px",
                      fontWeight: 500,
                      cursor: "pointer",
                      width: "fit-content",
                    }}
                  >
                    <Unlink size={14} />
                    <span>{gdriveLoading ? "Disconnecting..." : "Disconnect Google Drive"}</span>
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={async () => {
                    setGdriveLoading(true);
                    try {
                      const response = await apiFetch("/auth/gdrive/authorize", { method: "GET" });
                      const data = await response.json();
                      if (data.auth_url) {
                        window.location.href = data.auth_url;
                      }
                    } catch (err: any) {
                      setSettingsNotification({ type: "error", message: err.message || "Failed to start authorization." });
                      setGdriveLoading(false);
                    }
                  }}
                  disabled={gdriveLoading}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    padding: "10px 18px",
                    borderRadius: "8px",
                    background: "linear-gradient(135deg, rgba(99, 102, 241, 0.15), rgba(139, 92, 246, 0.15))",
                    border: "1px solid rgba(99, 102, 241, 0.3)",
                    color: "#a5b4fc",
                    fontSize: "13px",
                    fontWeight: 600,
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                    width: "100%",
                    justifyContent: "center",
                  }}
                >
                  {gdriveLoading ? (
                    <>
                      <Loader2 className={styles.spinner} size={16} />
                      <span>Redirecting to Google...</span>
                    </>
                  ) : (
                    <>
                      <Link2 size={16} />
                      <span>Connect Google Drive</span>
                    </>
                  )}
                </button>
              )}
            </div>

            {/* ── VDB Session Config ── */}
            <div style={{
              padding: "16px",
              borderRadius: "10px",
              background: "rgba(255,255,255,0.03)",
              border: "1px solid var(--glass-border)",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
                <ExternalLink size={18} style={{ color: "#94a3b8" }} />
                <strong style={{ fontSize: "14px" }}>VDB API Session</strong>
              </div>

              <p style={{ fontSize: "12px", color: "var(--text-muted)", marginBottom: "12px", lineHeight: 1.5 }}>
                If your VDB session expires, the scraper will fail. To renew, copy the search cURL command from your browser's DevTools Network tab and paste it below.
              </p>

              <div className={styles.instructionsBox}>
                <strong>How to get the cURL command:</strong>
                <ol>
                  <li>Open <code>app.vdbapp.com</code> in your browser and perform a search.</li>
                  <li>Press <code>F12</code> or right-click to open <strong>Developer Tools</strong>.</li>
                  <li>Go to the <strong>Network</strong> tab and select the <code>search_diamonds...</code> request.</li>
                  <li>Right-click it, select <strong>Copy</strong> &rarr; <strong>Copy as cURL</strong> (bash format).</li>
                </ol>
              </div>

              <form onSubmit={handleUpdateSession}>
                <textarea
                  className={styles.curlTextarea}
                  placeholder="Paste the curl command here (e.g. curl 'https://app.vdbapp.com/...' -H 'authorization: ...' ...)"
                  value={curlCommand}
                  onChange={(e) => setCurlCommand(e.target.value)}
                  disabled={updatingSettings}
                  required
                />

                <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "12px" }}>
                  <button
                    type="submit"
                    className={styles.modalSubmitBtn}
                    disabled={!curlCommand.trim() || updatingSettings}
                  >
                    {updatingSettings ? (
                      <>
                        <Loader2 className={styles.spinner} size={14} />
                        <span>Updating...</span>
                      </>
                    ) : (
                      <span>Update Session</span>
                    )}
                  </button>
                </div>
              </form>
            </div>

            <div className={styles.modalActions} style={{ marginTop: "16px" }}>
              <button
                type="button"
                className={styles.modalCancelBtn}
                onClick={() => setShowSettings(false)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
