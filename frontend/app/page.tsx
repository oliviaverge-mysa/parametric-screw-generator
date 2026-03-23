"use client";

import { useSession, signOut } from "next-auth/react";
import Script from "next/script";
import { useRef, useEffect } from "react";

const ASSET_VERSION = "20260323";

export default function Home() {
  const { data: session } = useSession();
  const containerRef = useRef<HTMLDivElement>(null);
  const injected = useRef(false);

  useEffect(() => {
    if (!containerRef.current || injected.current) return;
    injected.current = true;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `/assets/styles.css?v=${ASSET_VERSION}`;
    document.head.appendChild(link);
  }, []);

  return (
    <>
      <div ref={containerRef} id="app-root" suppressHydrationWarning>
        {/* Landing */}
        <section id="landing" className="landing">
          <div className="landing-overlay" />
          <div className="landing-content">
            <div className="landing-brand" aria-label="mysa">
              <img
                className="landing-logo"
                src="https://cdn.sanity.io/images/yi14n6wi/production/8d9313dc9d8252a660f20b1a0f47a3b7eeeccdd1-1260x572.png"
                alt="mysa"
              />
            </div>
            <h2>Fastener Generator</h2>
            <div className="landing-choices">
              <button id="landing-builder-btn" className="landing-choice-btn" type="button">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z" fill="currentColor" />
                </svg>
                <span className="landing-choice-label">Build Your Own</span>
                <span className="landing-choice-desc">Step-by-step spec builder</span>
              </button>
              <button id="landing-chatbot-btn" className="landing-choice-btn" type="button">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.2L4 17.2V4h16v12z" fill="currentColor" />
                </svg>
                <span className="landing-choice-label">Chatbot</span>
                <span className="landing-choice-desc">Describe or upload a photo</span>
              </button>
            </div>
            <form id="landing-form" className="landing-search" hidden>
              <input id="landing-input" type="text" placeholder="Describe the fastener you want..." autoComplete="off" />
              <input id="landing-image-input" type="file" accept="image/*" hidden />
              <button id="landing-send-btn" type="submit" hidden>Generate</button>
            </form>
          </div>
        </section>

        {/* Header */}
        <header id="global-header" className="global-header">
          <div className="global-header-left" aria-label="Sidebar controls">
            <button id="global-menu-btn" className="global-icon-btn sidebar-menu-toggle" type="button" aria-label="Toggle sidebar">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </button>
            <button className="brand-wordmark" id="brand-home-btn" type="button" aria-label="Back to home">
              <img
                className="brand-wordmark-logo brand-wordmark-logo-light"
                src="https://cdn.sanity.io/images/yi14n6wi/production/23c8f5899505ce623af8daccfced80de54904228-1260x572.png"
                alt="mysa"
              />
              <img
                className="brand-wordmark-logo brand-wordmark-logo-dark"
                src="https://cdn.sanity.io/images/yi14n6wi/production/8d9313dc9d8252a660f20b1a0f47a3b7eeeccdd1-1260x572.png"
                alt="mysa"
              />
            </button>
          </div>
          <div className="global-header-right" style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            {session?.user && (
              <>
                <span style={{ fontSize: "12px", opacity: 0.6 }}>{session.user.email}</span>
                <button
                  onClick={() => signOut()}
                  style={{
                    fontSize: "12px",
                    color: "#888",
                    background: "none",
                    border: "1px solid #444",
                    borderRadius: "6px",
                    padding: "4px 10px",
                    cursor: "pointer",
                  }}
                >
                  Sign out
                </button>
              </>
            )}
            <button id="theme-toggle-btn" className="theme-toggle" type="button" aria-label="Toggle dark mode">
              <span className="theme-toggle-thumb" aria-hidden="true" />
            </button>
          </div>
        </header>

        {/* App shell */}
        <div className="app">
          <aside className="sidebar">
            <nav id="view-nav" className="view-nav">
              <button id="nav-builder-btn" className="view-nav-btn active" type="button">Builder</button>
              <button id="nav-chat-btn" className="view-nav-btn" type="button">Chat</button>
            </nav>
            <section className="recent-fasteners">
              <div className="recent-header">Recent Fasteners</div>
              <div id="sidebar-recent-grid" className="sidebar-recent-grid" />
            </section>
            <div className="chats-header-row">
              <div className="recent-header chats-label">Chats</div>
              <div className="chats-actions">
                <button id="new-chat-btn" className="icon-action-btn" type="button" aria-label="New chat" title="New chat" />
                <button id="delete-chat-btn" className="icon-action-btn" type="button" aria-label="Delete current chat" title="Delete current chat">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M8.5 5h7l.75 1H20v2H4V6h3.75L8.5 5ZM6 9h12l-1 10H7L6 9Zm3 2v6h2v-6H9Zm4 0v6h2v-6h-2Z" fill="currentColor" />
                  </svg>
                </button>
              </div>
            </div>
            <div id="chat-list" className="chat-list" />
            <div id="sidebar-builder-form" className="sidebar-builder-form" hidden>
              <div id="builder-form" className="builder-form">
                <div className="builder-section" data-section="type">
                  <div className="builder-section-label">Fastener Type</div>
                  <div className="spec-btn-group" data-field="fastener_type">
                    <button type="button" className="spec-btn" data-value="screw">Screw</button>
                    <button type="button" className="spec-btn" data-value="bolt">Bolt</button>
                  </div>
                </div>
                <div className="builder-section" data-section="head">
                  <div className="builder-section-label">Head Type</div>
                  <div className="spec-btn-group" data-field="head_type">
                    <button type="button" className="spec-btn" data-value="flat">Flat</button>
                    <button type="button" className="spec-btn" data-value="pan">Pan</button>
                    <button type="button" className="spec-btn" data-value="button">Button</button>
                    <button type="button" className="spec-btn" data-value="hex">Hex</button>
                  </div>
                </div>
                <div className="builder-section" data-section="drive">
                  <div className="builder-section-label">Drive Type</div>
                  <div className="spec-btn-group" data-field="drive_type">
                    <button type="button" className="spec-btn" data-value="phillips">Phillips</button>
                    <button type="button" className="spec-btn" data-value="torx">Torx</button>
                    <button type="button" className="spec-btn" data-value="square">Square</button>
                    <button type="button" className="spec-btn" data-value="hex">Hex</button>
                    <button type="button" className="spec-btn" data-value="no drive">No Drive</button>
                  </div>
                </div>
                <div className="builder-section" data-section="slotted" id="builder-slotted-row" hidden>
                  <div className="builder-section-label">Slotted</div>
                  <div className="spec-btn-group" data-field="slotted">
                    <button type="button" className="spec-btn" data-value="no">No</button>
                    <button type="button" className="spec-btn" data-value="yes">Yes</button>
                  </div>
                </div>
                <div className="builder-section" data-section="threaded">
                  <div className="builder-section-label">Threaded</div>
                  <div className="spec-btn-group" data-field="threaded">
                    <button type="button" className="spec-btn" data-value="no">No</button>
                    <button type="button" className="spec-btn selected" data-value="yes">Yes</button>
                  </div>
                </div>
                <div className="builder-section" data-section="matching_nut">
                  <div className="builder-section-label">Matching Nut</div>
                  <div className="spec-btn-group" data-field="matching_nut">
                    <button type="button" className="spec-btn selected" data-value="no">No</button>
                    <button type="button" className="spec-btn" data-value="yes">Yes</button>
                  </div>
                </div>
                <div className="builder-section" data-section="nut_style" id="builder-nut-style-row" hidden>
                  <div className="builder-section-label">Nut Style</div>
                  <div className="spec-btn-group" data-field="nut_style">
                    <button type="button" className="spec-btn selected" data-value="hex">Hex</button>
                    <button type="button" className="spec-btn" data-value="square">Square</button>
                  </div>
                </div>
                <div className="builder-section" data-section="metric">
                  <div className="builder-section-label">ISO Designation <span className="builder-hint">(auto-fills dims)</span></div>
                  <div className="builder-input-row">
                    <input type="text" id="builder-metric" className="spec-input" placeholder="e.g. M8x1.25x40" />
                  </div>
                </div>
                <div className="builder-section" data-section="dimensions">
                  <div className="builder-section-label">Dimensions <span className="builder-hint">(mm)</span></div>
                  <div className="builder-dims-grid">
                    <label className="builder-dim"><span>Head Dia. <em>*</em></span><input type="number" step="any" className="spec-input" data-dim="head_d" placeholder="required" /></label>
                    <label className="builder-dim"><span>Head Height</span><input type="number" step="any" className="spec-input" data-dim="head_h" /></label>
                    <label className="builder-dim"><span>Shank Dia.</span><input type="number" step="any" className="spec-input" data-dim="shank_d" /></label>
                    <label className="builder-dim"><span>Root Dia.</span><input type="number" step="any" className="spec-input" data-dim="root_d" /></label>
                    <label className="builder-dim"><span>Shaft Len. <em>*</em></span><input type="number" step="any" className="spec-input" data-dim="length" placeholder="required" /></label>
                    <label className="builder-dim"><span>Tip Length</span><input type="number" step="any" className="spec-input" data-dim="tip_len" /></label>
                    <label className="builder-dim"><span>Pitch</span><input type="number" step="any" className="spec-input" data-dim="pitch" /></label>
                    <label className="builder-dim"><span>Thread Len.</span><input type="number" step="any" className="spec-input" data-dim="thread_len" /></label>
                  </div>
                  <div className="builder-thread-regions-row" id="builder-thread-regions-row">
                    <label className="builder-dim builder-dim-wide">
                      <span>Thread Regions <em className="builder-hint-inline">(overrides Thread Len.)</em></span>
                      <input type="text" id="builder-thread-regions" className="spec-input" placeholder="e.g. 3-5, 9-14  (0 = base of head)" />
                    </label>
                  </div>
                </div>
                <button type="button" id="builder-generate-btn" className="builder-generate-btn" disabled>Generate</button>
              </div>
            </div>
          </aside>

          <main className="main">
            <section id="chat-panel" className="chat-panel">
              <div id="messages" className="messages" />
              <form id="composer" className="composer">
                <input id="message-input" type="text" placeholder="Describe the fastener you want..." autoComplete="off" />
                <button id="image-upload-btn" className="icon-action-btn composer-image-btn" type="button" aria-label="Upload image" title="Upload image">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M9 3.5h6l1.3 2H20a2 2 0 0 1 2 2v10.5a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7.5a2 2 0 0 1 2-2h3.7l1.3-2Zm3 4.2a4.2 4.2 0 1 0 0 8.4 4.2 4.2 0 0 0 0-8.4Zm0 1.7a2.5 2.5 0 1 1 0 5.0 2.5 2.5 0 0 1 0-5.0Zm-6.7.1a1 1 0 1 0 0 2 1 1 0 0 0 0-2Z" fill="currentColor" />
                  </svg>
                </button>
                <input id="image-input" type="file" accept="image/*" hidden />
                <button type="submit">Send</button>
              </form>
            </section>
            <section id="builder-view" className="builder-view" hidden>
              <div id="builder-empty-state" className="builder-empty-state">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z" fill="currentColor" />
                </svg>
                <h3>Build Your Fastener</h3>
                <p>Select your specs in the sidebar and click Generate</p>
              </div>
              <div id="builder-preview" className="builder-preview" hidden>
                <div id="builder-preview-cards" className="builder-preview-cards" />
                <button type="button" id="builder-another-btn" className="builder-another-btn">Build Another</button>
              </div>
            </section>
            <section id="library-view" className="library-view" hidden>
              <div className="library-header">
                <h2>Fastener Library</h2>
                <p>Browse generated fasteners, rename cards, and jump back into any source chat.</p>
              </div>
              <div id="library-grid" className="library-grid" />
            </section>
          </main>
        </div>

        {/* Context menus */}
        <div id="chat-context-menu" className="chat-context-menu" hidden>
          <button id="ctx-rename-chat-btn" className="toolbar-btn" type="button">Rename Chat</button>
          <button id="ctx-delete-chat-btn" className="danger-btn" type="button">Delete Chat</button>
        </div>
        <div id="library-context-menu" className="chat-context-menu" hidden>
          <button id="ctx-rename-library-btn" className="toolbar-btn" type="button">Rename</button>
        </div>
      </div>

      <Script src={`/assets/app.js?v=${ASSET_VERSION}`} strategy="afterInteractive" />
    </>
  );
}
