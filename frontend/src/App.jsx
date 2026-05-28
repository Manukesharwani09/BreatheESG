import React, { useState, useEffect } from 'react';
import './App.css';

const API_BASE = 'http://localhost:8000/api';

function App() {
  const [records, setRecords] = useState([]);
  const [batches, setBatches] = useState([]);
  const [stats, setStats] = useState({
    total_approved_carbon: 0,
    total_hypothetical_carbon: 0,
    total_rows: 0,
    approved_rows: 0,
    flagged_rows: 0,
    pending_rows: 0,
    approval_rate: 0,
    flagged_rate: 0,
    scope_breakdown: [],
    source_breakdown: [],
    category_breakdown: []
  });
  
  // Selection & Filters
  const [selectedSource, setSelectedSource] = useState('ALL'); // ALL, SAP, UTILITY, TRAVEL
  const [selectedStatus, setSelectedStatus] = useState('ALL'); // ALL, PENDING, APPROVED, FLAGGED
  const [selectedScope, setSelectedScope] = useState('ALL'); // ALL, 1, 2, 3
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedRecordId, setSelectedRecordId] = useState(null);
  const [selectedRows, setSelectedRows] = useState([]);
  
  // UI State
  const [uploadSourceType, setUploadSourceType] = useState('SAP');
  const [selectedFile, setSelectedFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState({ text: '', type: '' });
  const [activeTab, setActiveTab] = useState('review'); // review, batches, config
  
  // Drawer Editing
  const [editQty, setEditQty] = useState('');
  const [editUnit, setEditUnit] = useState('');
  const [editStatus, setEditStatus] = useState('');
  const [editReason, setEditReason] = useState('');
  const [isEditing, setIsEditing] = useState(false);

  // Fetch initial data
  const fetchData = async () => {
    try {
      // 1. Fetch records
      let url = `${API_BASE}/records/`;
      const queryParams = [];
      if (selectedSource !== 'ALL') queryParams.push(`source=${selectedSource}`);
      if (selectedStatus !== 'ALL') queryParams.push(`status=${selectedStatus}`);
      if (selectedScope !== 'ALL') queryParams.push(`scope=${selectedScope}`);
      if (queryParams.length > 0) {
        url += `?${queryParams.join('&')}`;
      }
      
      const resRecords = await fetch(url);
      if (resRecords.ok) {
        const data = await resRecords.json();
        setRecords(data);
      }

      // 2. Fetch stats
      const resStats = await fetch(`${API_BASE}/stats/`);
      if (resStats.ok) {
        const data = await resStats.json();
        setStats(data);
      }

      // 3. Fetch batches
      const resBatches = await fetch(`${API_BASE}/batches/`);
      if (resBatches.ok) {
        const data = await resBatches.json();
        setBatches(data);
      }
    } catch (err) {
      console.warn("Backend server not reachable, using simulated client state.", err);
    }
  };

  useEffect(() => {
    fetchData();
  }, [selectedSource, selectedStatus, selectedScope]);

  // Seed simulated dataset
  const handleSeedAll = async () => {
    setIsUploading(true);
    setUploadMessage({ text: 'Generating enterprise dataset...', type: 'info' });
    try {
      const res = await fetch(`${API_BASE}/simulation/seed_all/`, {
        method: 'POST',
      });
      if (res.ok) {
        setUploadMessage({ text: ' enterprise dataset successfully synchronized!', type: 'success' });
        fetchData();
      } else {
        setUploadMessage({ text: 'Failed to seed simulation data.', type: 'danger' });
      }
    } catch (err) {
      setUploadMessage({ text: 'Error connecting to backend server.', type: 'danger' });
    } finally {
      setIsUploading(false);
    }
  };

  // Upload handler
  const handleFileUpload = async (e) => {
    e.preventDefault();
    if (!selectedFile) {
      setUploadMessage({ text: 'Please select a file to ingest.', type: 'warning' });
      return;
    }

    setIsUploading(true);
    setUploadMessage({ text: 'Uploading file to ingestion engine...', type: 'info' });

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('source_type', uploadSourceType);
    formData.append('uploaded_by', 'Sustainability Auditor');

    try {
      const res = await fetch(`${API_BASE}/batches/ingest/`, {
        method: 'POST',
        body: formData,
      });

      if (res.ok) {
        const data = await res.json();
        setUploadMessage({ 
          text: `Batch ingested successfully! Created batch #${data.id} containing raw rows.`, 
          type: 'success' 
        });
        setSelectedFile(null);
        // Reset file input
        document.getElementById('file-uploader-input').value = '';
        fetchData();
      } else {
        const errData = await res.json();
        setUploadMessage({ text: `Ingestion failed: ${errData.error || 'Unknown error'}`, type: 'danger' });
      }
    } catch (err) {
      setUploadMessage({ text: 'Error uploading file to server.', type: 'danger' });
    } finally {
      setIsUploading(false);
    }
  };

  // Record actions: Approve
  const handleApprove = async (id, reason = "Analyst Sign-off") => {
    try {
      const res = await fetch(`${API_BASE}/records/${id}/approve/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reason: reason,
          action_by: 'Lead Sustainability Analyst'
        })
      });
      if (res.ok) {
        fetchData();
        // Update local selection drawer if open
        if (selectedRecordId === id) {
          const updated = await res.json();
          // Force state update
          setSelectedRecordId(null);
          setTimeout(() => setSelectedRecordId(id), 50);
        }
      }
    } catch (err) {
      alert("Error approving record");
    }
  };

  // Record actions: Flag
  const handleFlag = async (id, reason) => {
    if (!reason) {
      alert("Please specify a reason for flagging this record.");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/records/${id}/flag/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reason: reason,
          action_by: 'Lead Sustainability Analyst'
        })
      });
      if (res.ok) {
        fetchData();
        setEditReason('');
        if (selectedRecordId === id) {
          setSelectedRecordId(null);
          setTimeout(() => setSelectedRecordId(id), 50);
        }
      }
    } catch (err) {
      alert("Error flagging record");
    }
  };

  // Record actions: Edit/Override
  const handleEditSubmit = async (e) => {
    e.preventDefault();
    if (!editReason) {
      alert("Please provide an override explanation reason for the audit log.");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/records/${selectedRecordId}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          normalized_quantity: editQty,
          normalized_unit: editUnit,
          reason: editReason,
          action_by: 'Lead Sustainability Analyst'
        })
      });

      if (res.ok) {
        fetchData();
        setIsEditing(false);
        setEditReason('');
        // Reload drawer state
        setSelectedRecordId(null);
        setTimeout(() => setSelectedRecordId(selectedRecordId), 50);
      } else {
        const data = await res.json();
        alert(`Override failed: ${data.error || 'Invalid inputs'}`);
      }
    } catch (err) {
      alert("Error overriding record values");
    }
  };

  // Bulk actions: Approve
  const handleBulkApprove = async () => {
    if (selectedRows.length === 0) return;
    if (!confirm(`Are you sure you want to approve all ${selectedRows.length} selected records? This will lock them permanently for auditing.`)) return;

    try {
      const res = await fetch(`${API_BASE}/records/bulk_approve/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ids: selectedRows,
          action_by: 'Lead Sustainability Analyst',
          reason: 'Bulk Sign-off from Main Dashboard'
        })
      });

      if (res.ok) {
        fetchData();
        setSelectedRows([]);
      } else {
        alert("Bulk approval failed");
      }
    } catch (err) {
      alert("Error in bulk approval");
    }
  };

  const toggleSelectRow = (id) => {
    if (selectedRows.includes(id)) {
      setSelectedRows(selectedRows.filter(rId => rId !== id));
    } else {
      setSelectedRows([...selectedRows, id]);
    }
  };

  const toggleSelectAll = () => {
    const visibleIds = filteredRecords.map(r => r.id);
    const allSelected = visibleIds.every(id => selectedRows.includes(id));
    if (allSelected) {
      setSelectedRows(selectedRows.filter(id => !visibleIds.includes(id)));
    } else {
      setSelectedRows([...new Set([...selectedRows, ...visibleIds])]);
    }
  };

  // Local Search & Filters
  const selectedRecord = records.find(r => r.id === selectedRecordId);

  const filteredRecords = records.filter(rec => {
    const matchesSearch = 
      (rec.category || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
      (rec.original_quantity || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
      (rec.original_unit || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
      (rec.validation_flags || []).some(f => f.toLowerCase().includes(searchQuery.toLowerCase())) ||
      rec.id.toString().includes(searchQuery);
    return matchesSearch;
  });

  return (
    <div className="app-container">
      {/* 1. STUNNING NAVIGATION HEADER */}
      <header className="main-header glass-panel fade-in">
        <div className="logo-group">
          <div className="logo-icon">🌿</div>
          <div className="logo-text">
            <h1>Breathe ESG</h1>
            <span className="subtitle">Enterprise Data Ingestion & Normalization</span>
          </div>
        </div>

        <nav className="header-nav">
          <button 
            className={`nav-btn ${activeTab === 'review' ? 'active' : ''}`}
            onClick={() => setActiveTab('review')}
          >
            📋 Analyst Review
          </button>
          <button 
            className={`nav-btn ${activeTab === 'batches' ? 'active' : ''}`}
            onClick={() => setActiveTab('batches')}
          >
            📦 Ingestion Batches
          </button>
        </nav>

        <div className="system-status">
          <button className="btn-seed" onClick={handleSeedAll} disabled={isUploading}>
            🚀 Seed Live Demo Data
          </button>
          <div className="tenant-badge">
            <span className="dot"></span>
            Acme Corp (Tenant #1)
          </div>
        </div>
      </header>

      {/* 2. GLOWING KPI CARDS */}
      <section className="kpi-grid fade-in">
        <div className="kpi-card glass-panel count-carbon">
          <div className="kpi-icon">🌍</div>
          <div className="kpi-content">
            <span className="kpi-label">Approved Carbon Footprint</span>
            <h2 className="kpi-value">{(stats.total_approved_carbon / 1000).toFixed(2)} <span className="unit">t CO2e</span></h2>
            <p className="kpi-desc">Locked and verified for auditing</p>
          </div>
        </div>

        <div className="kpi-card glass-panel count-pending">
          <div className="kpi-icon">⌛</div>
          <div className="kpi-content">
            <span className="kpi-label">Pending Review</span>
            <h2 className="kpi-value">{stats.pending_rows} <span className="unit">rows</span></h2>
            <p className="kpi-desc">Awaiting analyst verification</p>
          </div>
        </div>

        <div className="kpi-card glass-panel count-flagged">
          <div className="kpi-icon">⚠️</div>
          <div className="kpi-content">
            <span className="kpi-label">Anomalies Detected</span>
            <h2 className="kpi-value">{stats.flagged_rows} <span className="unit">flags</span></h2>
            <p className="kpi-desc">Requires manual lookup & overrides</p>
          </div>
        </div>

        <div className="kpi-card glass-panel count-rate">
          <div className="kpi-icon">🎯</div>
          <div className="kpi-content">
            <span className="kpi-label">Audit-Ready Rate</span>
            <h2 className="kpi-value">{stats.approval_rate.toFixed(1)}%</h2>
            <div className="progress-bar-container">
              <div className="progress-bar" style={{ width: `${stats.approval_rate}%` }}></div>
            </div>
          </div>
        </div>
      </section>

      {/* MAIN APPLICATION TAB LAYOUT */}
      {activeTab === 'review' && (
        <div className="dashboard-layout fade-in">
          {/* 3. CONTROL CENTER: FILTERS & BULK ACTIONS */}
          <section className="controls-panel glass-panel">
            <div className="controls-header">
              <h3>⚡ Data Control Center</h3>
            </div>
            
            <div className="filters-group">
              <div className="filter-item">
                <label>Data Source Type</label>
                <div className="btn-toggle-group">
                  <button className={selectedSource === 'ALL' ? 'active' : ''} onClick={() => setSelectedSource('ALL')}>All</button>
                  <button className={selectedSource === 'SAP' ? 'active' : ''} onClick={() => setSelectedSource('SAP')}>SAP (Scope 1)</button>
                  <button className={selectedSource === 'UTILITY' ? 'active' : ''} onClick={() => setSelectedSource('UTILITY')}>Utility (Scope 2)</button>
                  <button className={selectedSource === 'TRAVEL' ? 'active' : ''} onClick={() => setSelectedSource('TRAVEL')}>Travel (Scope 3)</button>
                </div>
              </div>

              <div className="filter-item">
                <label>Compliance Status</label>
                <div className="btn-toggle-group">
                  <button className={selectedStatus === 'ALL' ? 'active' : ''} onClick={() => setSelectedStatus('ALL')}>All</button>
                  <button className={selectedStatus === 'PENDING' ? 'active' : ''} onClick={() => setSelectedStatus('PENDING')}>Pending</button>
                  <button className={selectedStatus === 'APPROVED' ? 'active' : ''} onClick={() => setSelectedStatus('APPROVED')}>Approved</button>
                  <button className={selectedStatus === 'FLAGGED' ? 'active' : ''} onClick={() => setSelectedStatus('FLAGGED')}>Flagged</button>
                </div>
              </div>

              <div className="filter-item">
                <label>Greenhouse Gas Scope</label>
                <div className="btn-toggle-group">
                  <button className={selectedScope === 'ALL' ? 'active' : ''} onClick={() => setSelectedScope('ALL')}>All Scopes</button>
                  <button className={selectedScope === '1' ? 'active' : ''} onClick={() => setSelectedScope('1')}>Scope 1</button>
                  <button className={selectedScope === '2' ? 'active' : ''} onClick={() => setSelectedScope('2')}>Scope 2</button>
                  <button className={selectedScope === '3' ? 'active' : ''} onClick={() => setSelectedScope('3')}>Scope 3</button>
                </div>
              </div>
            </div>

            <div className="search-and-actions">
              <div className="search-wrapper">
                <span className="search-icon">🔍</span>
                <input 
                  type="text" 
                  placeholder="Search by material code, meter reading gap, warning description..." 
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>

              {selectedRows.length > 0 && (
                <div className="bulk-actions fade-in">
                  <span className="selected-count">Selected: <strong>{selectedRows.length}</strong> items</span>
                  <button className="btn-bulk-approve" onClick={handleBulkApprove}>
                    ✔️ Bulk Sign-off
                  </button>
                </div>
              )}
            </div>
          </section>

          {/* 4. DATA REVIEW GRID TABLE */}
          <section className="table-wrapper glass-panel">
            <table className="review-table">
              <thead>
                <tr>
                  <th width="40px" className="align-center">
                    <input 
                      type="checkbox" 
                      onChange={toggleSelectAll}
                      checked={filteredRecords.length > 0 && filteredRecords.every(r => selectedRows.includes(r.id))}
                    />
                  </th>
                  <th width="80px">ID</th>
                  <th>Activity Date</th>
                  <th>Source File</th>
                  <th>Scope / Cat</th>
                  <th>Raw Input</th>
                  <th>Normalized Activity</th>
                  <th>Calculated Footprint</th>
                  <th>Status</th>
                  <th>Flags / Anomaly Checks</th>
                  <th width="100px" className="align-center">Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredRecords.length === 0 ? (
                  <tr>
                    <td colSpan="11" className="empty-row-message">
                      <div className="empty-container">
                        <h3>No records found matching current query parameters.</h3>
                        <p>Try synchronizing simulated corporate data or upload a raw file.</p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  filteredRecords.map(rec => {
                    const isSelected = selectedRows.includes(rec.id);
                    return (
                      <tr 
                        key={rec.id} 
                        className={`${isSelected ? 'selected' : ''} ${selectedRecordId === rec.id ? 'active-row' : ''}`}
                      >
                        <td className="align-center">
                          <input 
                            type="checkbox" 
                            checked={isSelected}
                            onChange={() => toggleSelectRow(rec.id)}
                            disabled={rec.is_locked}
                          />
                        </td>
                        <td className="cell-id">#{rec.id}</td>
                        <td>{rec.activity_date}</td>
                        <td className="cell-source">{rec.raw_payload ? '📂 ' + (rec.category === 'electricity' ? 'Utility Bill' : rec.category === 'fuel' ? 'SAP PO' : 'Concur Trip') : 'API sync'}</td>
                        <td>
                          <span className={`badge badge-scope badge-scope-${rec.scope}`}>
                            S{rec.scope}
                          </span>
                          <span className="badge-cat">{rec.category}</span>
                        </td>
                        <td className="cell-raw">{rec.original_quantity} {rec.original_unit}</td>
                        <td className="cell-norm">
                          {rec.normalized_quantity ? rec.normalized_quantity.toLocaleString(undefined, {maximumFractionDigits:2}) : '0'} {rec.normalized_unit}
                        </td>
                        <td className="cell-emissions">
                          {rec.calculated_emissions ? (
                            <strong>
                              {(rec.calculated_emissions).toLocaleString(undefined, {maximumFractionDigits:1})} kg CO2e
                            </strong>
                          ) : (
                            <span className="math-error">Calculation Error</span>
                          )}
                        </td>
                        <td>
                          <span className={`badge badge-${rec.status.toLowerCase()}`}>
                            {rec.status}
                          </span>
                        </td>
                        <td>
                          <div className="flags-list">
                            {rec.validation_flags.length === 0 ? (
                              <span className="clean-check">✅ Clean Check</span>
                            ) : (
                              rec.validation_flags.map((flag, i) => (
                                <span key={i} className="flag-item" title="Click detail pane for engineering breakdown">
                                  ⚠️ {flag}
                                </span>
                              ))
                            )}
                          </div>
                        </td>
                        <td className="align-center">
                          <button 
                            className="btn-drill"
                            onClick={() => {
                              setSelectedRecordId(rec.id);
                              setEditQty(rec.normalized_quantity || '');
                              setEditUnit(rec.normalized_unit || '');
                              setEditStatus(rec.status);
                              setIsEditing(false);
                            }}
                          >
                            Drill Down 🔍
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </section>

          {/* 5. IMMERSIVE COMPLIANCE SIDEBAR DRAWER */}
          {selectedRecord && (
            <div className="drawer-overlay fade-in" onClick={() => setSelectedRecordId(null)}>
              <div className="drawer-panel glass-panel" onClick={(e) => e.stopPropagation()}>
                <div className="drawer-header">
                  <div className="header-meta">
                    <span className={`badge badge-scope badge-scope-${selectedRecord.scope}`}>Scope {selectedRecord.scope}</span>
                    <span className="drawer-id">Record #{selectedRecord.id}</span>
                  </div>
                  <h2>Analyst Drill Down & Compliance Audit</h2>
                  <button className="btn-close" onClick={() => setSelectedRecordId(null)}>✖</button>
                </div>

                <div className="drawer-body">
                  {/* Validation Flags Alert */}
                  {selectedRecord.validation_flags.length > 0 && (
                    <div className="drawer-section anomaly-alert">
                      <h4>⚠️ Anomaly Flags Detected</h4>
                      <ul>
                        {selectedRecord.validation_flags.map((flag, idx) => (
                          <li key={idx}>
                            <strong>{flag}:</strong> {
                              flag === 'UNKNOWN_PLANT' ? 'The plant code Werk in SAP was not found in the baseline organization lookups.' :
                              flag === 'INVALID_UNIT' ? 'The system encountered an unresolvable unit (e.g. FL) which has no standard GHG scale.' :
                              flag === 'NEGATIVE_QUANTITY' ? 'Activity amount cannot be negative or zero.' :
                              flag === 'METER_READ_GAP' ? 'Calculated difference between meter readings does not match usage.' :
                              flag === 'OVERLAPPING_BILL' ? 'Billing cycle overlap detected with an existing meter bill.' :
                              'General validation warning.'
                            }
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Math Audit Trail */}
                  <div className="drawer-section calculation-trail">
                    <h3>🔬 Steps in Carbon Normalization Science</h3>
                    <div className="trail-block">
                      <div className="trail-item">
                        <span className="step-label">Formula Base</span>
                        <p className="step-content formula">{selectedRecord.calculation_trail?.formula}</p>
                      </div>
                      <div className="trail-item">
                        <span className="step-label">Conversion Phase</span>
                        <p className="step-content">{selectedRecord.calculation_trail?.quantity_step}</p>
                      </div>
                      <div className="trail-item">
                        <span className="step-label">Emission Factor Matching</span>
                        <p className="step-content">{selectedRecord.calculation_trail?.factor_step}</p>
                      </div>
                      <div className="trail-item">
                        <span className="step-label">Product Result</span>
                        <p className="step-content result">{selectedRecord.calculation_trail?.math_step}</p>
                      </div>
                    </div>
                  </div>

                  {/* Edit/Override values form */}
                  <div className="drawer-section override-values">
                    <h3>✍️ Audit Overrides & Value Edits</h3>
                    {selectedRecord.is_locked ? (
                      <div className="locked-message-box">
                        <span className="lock-icon">🔒</span>
                        <div>
                          <strong>Locked for Auditing</strong>
                          <p>This row has been signed off and locked. It is fully immutable for compliance security.</p>
                        </div>
                      </div>
                    ) : (
                      <>
                        {!isEditing ? (
                          <div className="edit-trigger-box">
                            <p>Are the normalized calculations incorrect due to raw file typos? You can manually override values here.</p>
                            <button className="btn-edit-trigger" onClick={() => setIsEditing(true)}>
                              ✏️ Manually Override Quantities
                            </button>
                          </div>
                        ) : (
                          <form className="edit-form fade-in" onSubmit={handleEditSubmit}>
                            <div className="form-group">
                              <label>Normalized Quantity</label>
                              <input 
                                type="number" 
                                step="any"
                                value={editQty} 
                                onChange={(e) => setEditQty(e.target.value)} 
                                required
                              />
                            </div>
                            <div className="form-group">
                              <label>Normalized Unit</label>
                              <input 
                                type="text" 
                                value={editUnit} 
                                onChange={(e) => setEditUnit(e.target.value)} 
                                required
                              />
                            </div>
                            <div className="form-group">
                              <label>Override Reason (Mandatory for compliance log)</label>
                              <textarea 
                                placeholder="Explain why you are modifying this record. This creates an permanent trail for auditors..."
                                value={editReason}
                                onChange={(e) => setEditReason(e.target.value)}
                                required
                              />
                            </div>
                            <div className="edit-buttons">
                              <button type="submit" className="btn-save">Save Override</button>
                              <button type="button" className="btn-cancel" onClick={() => setIsEditing(false)}>Cancel</button>
                            </div>
                          </form>
                        )}
                      </>
                    )}
                  </div>

                  {/* Source of Truth Raw Payload */}
                  <div className="drawer-section raw-payload">
                    <h3>📂 Source of Truth: Raw Upload Data</h3>
                    <pre className="json-box">
                      {JSON.stringify(selectedRecord.raw_payload, null, 2)}
                    </pre>
                  </div>

                  {/* Immutable Audit Log Trail */}
                  <div className="drawer-section audit-trail">
                    <h3>📜 Permanent Audit Logs</h3>
                    <div className="audit-timeline">
                      <div className="timeline-item origin">
                        <span className="time">{new Date(selectedRecord.created_at).toLocaleString()}</span>
                        <strong className="author">System Parser</strong>
                        <p className="action">Raw record ingested and parsed to NormalizedRecord.</p>
                      </div>
                      
                      {selectedRecord.audit_logs && selectedRecord.audit_logs.map((log) => (
                        <div key={log.id} className={`timeline-item ${log.action_type.toLowerCase()}`}>
                          <span className="time">{new Date(log.timestamp).toLocaleString()}</span>
                          <strong className="author">{log.action_by}</strong>
                          <span className="log-action-badge">{log.action_type}</span>
                          <p className="action-reason">"{log.reason}"</p>
                          {log.old_values && (
                            <div className="audit-diff">
                              <span><strong>Original Qty:</strong> {log.old_values.normalized_quantity} {log.old_values.normalized_unit}</span>
                              <span>➡️ <strong>New Qty:</strong> {log.new_values.normalized_quantity} {log.new_values.normalized_unit}</span>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Drawer Footer controls */}
                {!selectedRecord.is_locked && (
                  <div className="drawer-footer">
                    <button className="btn-approve" onClick={() => handleApprove(selectedRecord.id)}>
                      ✔️ Approve & Lock
                    </button>
                    
                    <button 
                      className="btn-flag-drawer" 
                      onClick={() => {
                        const reason = prompt("Enter flagging reasoning:");
                        if (reason) handleFlag(selectedRecord.id, reason);
                      }}
                    >
                      ⚠️ Flag Anomaly
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === 'batches' && (
        <div className="batches-layout fade-in">
          {/* Ingestion Console */}
          <section className="upload-section glass-panel">
            <h3>📂 Corporate Data Ingestion Console</h3>
            <p className="section-desc">Drag and drop client SAP reports, utility portal downloads, or synchronized travel agency records to normalize them.</p>

            {uploadMessage.text && (
              <div className={`message-banner message-${uploadMessage.type} fade-in`}>
                {uploadMessage.text}
              </div>
            )}

            <form className="upload-form" onSubmit={handleFileUpload}>
              <div className="form-row">
                <div className="form-input-group">
                  <label>Data Ingest System</label>
                  <select value={uploadSourceType} onChange={(e) => setUploadSourceType(e.target.value)}>
                    <option value="SAP">SAP Procurement & Fuels (CSV)</option>
                    <option value="UTILITY">Utility Energy Portal (CSV)</option>
                    <option value="TRAVEL">Corporate Travel Flights/Hotels (JSON)</option>
                  </select>
                </div>

                <div className="form-input-group file-field">
                  <label>Select CSV or JSON Document</label>
                  <input 
                    id="file-uploader-input"
                    type="file" 
                    onChange={(e) => setSelectedFile(e.target.files[0])}
                    required
                  />
                </div>

                <button type="submit" className="btn-upload" disabled={isUploading}>
                  {isUploading ? 'Ingesting...' : 'Ingest and Normalize ⚡'}
                </button>
              </div>
            </form>
          </section>

          {/* Batches Log List */}
          <section className="batches-list glass-panel">
            <h3>📦 Historic Ingestion Sessions</h3>
            <table className="batches-table">
              <thead>
                <tr>
                  <th width="80px">Batch ID</th>
                  <th>Ingest System</th>
                  <th>Document Name</th>
                  <th>Triggered By</th>
                  <th>Activity Timestamp</th>
                  <th>Validation Result</th>
                </tr>
              </thead>
              <tbody>
                {batches.length === 0 ? (
                  <tr>
                    <td colSpan="6" className="align-center empty-cell">No ingestion history found. Try seeding simulated data.</td>
                  </tr>
                ) : (
                  batches.map(batch => (
                    <tr key={batch.id}>
                      <td className="cell-id">#{batch.id}</td>
                      <td><strong>{batch.source_type}</strong></td>
                      <td><span className="file-icon">📄</span> {batch.file_name}</td>
                      <td>{batch.uploaded_by}</td>
                      <td>{new Date(batch.uploaded_at).toLocaleString()}</td>
                      <td>
                        <span className={`badge-batch-status status-${batch.status.toLowerCase()}`}>
                          {batch.status === 'COMPLETED' ? '✔️ Success' : batch.status === 'FAILED' ? '✖ Failed' : '⌛ Processing'}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  );
}

export default App;
