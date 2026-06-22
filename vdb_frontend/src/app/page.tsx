"use client";

import React, { useState, useEffect } from "react";
import Login from "@/components/Login";
import Dashboard from "@/components/Dashboard";
import { getStoredToken } from "@/utils/api";
import { Loader2 } from "lucide-react";

export default function Home() {
  const [mounted, setMounted] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [username, setUsername] = useState("");

  useEffect(() => {
    setMounted(true);
    const token = getStoredToken();
    const storedUsername = localStorage.getItem("vdb_username") || "";

    if (token) {
      setIsAuthenticated(true);
      setUsername(storedUsername);
    } else {
      setIsAuthenticated(false);
    }
  }, []);

  const handleLoginSuccess = (user: string) => {
    setIsAuthenticated(true);
    setUsername(user);
  };

  const handleLogout = () => {
    setIsAuthenticated(false);
    setUsername("");
  };

  // Prevent hydration flicker on first server render
  if (!mounted) {
    return (
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        backgroundColor: "#0a0b10",
        color: "#94a3b8"
      }}>
        <Loader2 className="animate-spin" size={32} style={{ animation: "spin 0.8s linear infinite" }} />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Login onLoginSuccess={handleLoginSuccess} />;
  }

  return <Dashboard username={username} onLogout={handleLogout} />;
}
