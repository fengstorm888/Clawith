import { useState, useRef, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { agentTeamApi } from '../services/api';
import type { AgentTeam, TeamMessage } from '../types';

interface TeamChatPanelProps {
    team: AgentTeam;
    sessionId: string | null;
    onSessionCreated: (sessionId: string) => void;
}

interface StreamingExpert {
    speaker_agent_id: string;
    speaker_name: string;
    member_role: string;
    content: string;
    done: boolean;
}

interface RoundData {
    round: number;
    userMessage: string;
    experts: StreamingExpert[];
    coordinatorContent: string;
    coordinatorDone: boolean;
}

export default function TeamChatPanel({ team, sessionId, onSessionCreated }: TeamChatPanelProps) {
    const [rounds, setRounds] = useState<RoundData[]>([]);
    const [input, setInput] = useState('');
    const [isStreaming, setIsStreaming] = useState(false);
    const wsRef = useRef<WebSocket | null>(null);
    const scrollRef = useRef<HTMLDivElement>(null);
    const currentSessionId = useRef<string | null>(sessionId);

    // Load historical messages
    const { data: messages = [] } = useQuery({
        queryKey: ['team-messages', team.id, sessionId],
        queryFn: () => sessionId ? agentTeamApi.messages(team.id, sessionId) : Promise.resolve([]),
        enabled: !!sessionId,
    });

    // Convert historical messages to rounds
    useEffect(() => {
        if (messages.length === 0) return;
        const roundMap = new Map<number, RoundData>();
        for (const msg of messages as TeamMessage[]) {
            const r = msg.round_number;
            if (!roundMap.has(r)) {
                roundMap.set(r, { round: r, userMessage: '', experts: [], coordinatorContent: '', coordinatorDone: false });
            }
            const rd = roundMap.get(r)!;
            if (msg.speaker_type === 'user') {
                rd.userMessage = msg.content;
            } else if (msg.speaker_type === 'expert') {
                rd.experts.push({
                    speaker_agent_id: msg.speaker_agent_id || '',
                    speaker_name: msg.speaker_name,
                    member_role: msg.member_role || '',
                    content: msg.content,
                    done: true,
                });
            } else if (msg.speaker_type === 'coordinator') {
                rd.coordinatorContent = msg.content;
                rd.coordinatorDone = true;
            }
        }
        setRounds(Array.from(roundMap.values()));
    }, [messages]);

    // Auto-scroll
    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [rounds]);

    const connectWs = useCallback((sid: string) => {
        if (wsRef.current) {
            wsRef.current.close();
        }
        const token = localStorage.getItem('token');
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const ws = new WebSocket(`${protocol}//${host}/api/ws/team-chat/${team.id}?token=${token}&session_id=${sid}`);
        wsRef.current = ws;

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            handleWsMessage(data);
        };

        ws.onclose = () => {
            wsRef.current = null;
        };
    }, [team.id]);

    // Connect when sessionId changes
    useEffect(() => {
        if (sessionId && sessionId !== currentSessionId.current) {
            currentSessionId.current = sessionId;
            connectWs(sessionId);
        }
        return () => {
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };
    }, [sessionId, connectWs]);

    const handleWsMessage = (data: any) => {
        switch (data.type) {
            case 'connected':
                if (data.session_id && !currentSessionId.current) {
                    currentSessionId.current = data.session_id;
                    onSessionCreated(data.session_id);
                }
                break;
            case 'expert_start':
                setRounds(prev => {
                    const last = prev[prev.length - 1];
                    if (!last || last.coordinatorDone || last.experts.every(e => e.done)) {
                        // Shouldn't happen — round is created on send
                        return prev;
                    }
                    last.experts.push({
                        speaker_agent_id: data.speaker_agent_id,
                        speaker_name: data.speaker_name,
                        member_role: data.member_role,
                        content: '',
                        done: false,
                    });
                    return [...prev];
                });
                break;
            case 'expert_chunk':
                setRounds(prev => prev.map(r => ({
                    ...r,
                    experts: r.experts.map(e =>
                        e.speaker_agent_id === data.speaker_agent_id && !e.done
                            ? { ...e, content: e.content + data.content }
                            : e
                    ),
                })));
                break;
            case 'expert_done':
                setRounds(prev => prev.map(r => ({
                    ...r,
                    experts: r.experts.map(e =>
                        e.speaker_agent_id === data.speaker_agent_id ? { ...e, done: true } : e
                    ),
                })));
                break;
            case 'coordinator_start':
                // Mark coordinator as starting
                break;
            case 'coordinator_chunk':
                setRounds(prev => {
                    if (prev.length === 0) return prev;
                    const last = { ...prev[prev.length - 1] };
                    last.coordinatorContent += data.content;
                    return [...prev.slice(0, -1), last];
                });
                break;
            case 'coordinator_done':
                setRounds(prev => {
                    if (prev.length === 0) return prev;
                    const last = { ...prev[prev.length - 1] };
                    last.coordinatorDone = true;
                    return [...prev.slice(0, -1), last];
                });
                break;
            case 'round_done':
                setIsStreaming(false);
                break;
            case 'error':
                console.error('Team chat error:', data.content);
                setIsStreaming(false);
                break;
        }
    };

    const sendMessage = async () => {
        if (!input.trim() || isStreaming) return;

        // Ensure we have a session
        let sid = currentSessionId.current;
        if (!sid) {
            const session = await agentTeamApi.createSession(team.id);
            sid = session.id;
            currentSessionId.current = sid;
            onSessionCreated(sid!);
            connectWs(sid!);
            // Wait for WS to connect
            await new Promise(resolve => setTimeout(resolve, 500));
        }

        // Create new round
        const newRound: RoundData = {
            round: rounds.length + 1,
            userMessage: input.trim(),
            experts: [],
            coordinatorContent: '',
            coordinatorDone: false,
        };
        setRounds(prev => [...prev, newRound]);
        setInput('');
        setIsStreaming(true);

        // Send via WebSocket
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({
                type: 'message',
                content: input.trim(),
                session_id: sid,
            }));
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* Messages */}
            <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>
                {rounds.length === 0 && (
                    <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-tertiary)' }}>
                        {team.welcome_message || `向「${team.name}」专家团提问，多位专家将协作回答`}
                    </div>
                )}
                {rounds.map((rd, idx) => (
                    <div key={idx} style={{ marginBottom: '24px' }}>
                        {/* User question */}
                        <div style={{
                            display: 'flex', justifyContent: 'flex-end', marginBottom: '16px',
                        }}>
                            <div style={{
                                maxWidth: '70%', padding: '10px 14px', borderRadius: '12px 12px 4px 12px',
                                background: 'var(--accent-primary, #4f46e5)', color: '#fff', fontSize: '14px',
                            }}>
                                {rd.userMessage}
                            </div>
                        </div>

                        {/* Expert responses */}
                        {rd.experts.length > 0 && (
                            <div style={{ marginBottom: '8px' }}>
                                <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '8px' }}>
                                    专家发言（{rd.experts.length}）
                                </div>
                                <div style={{ display: 'grid', gap: '8px' }}>
                                    {rd.experts.map((expert, eIdx) => (
                                        <div key={eIdx} style={{
                                            padding: '12px', borderRadius: '10px',
                                            background: 'var(--bg-secondary, #f8f9fa)',
                                            border: '1px solid var(--border-light, #e5e7eb)',
                                        }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                                                <div style={{
                                                    width: '24px', height: '24px', borderRadius: '6px',
                                                    background: 'var(--accent-secondary, #6366f1)', color: '#fff',
                                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                    fontSize: '12px', fontWeight: 600,
                                                }}>
                                                    {expert.speaker_name.charAt(0)}
                                                </div>
                                                <span style={{ fontSize: '13px', fontWeight: 600 }}>{expert.speaker_name}</span>
                                                {expert.member_role && (
                                                    <span style={{
                                                        padding: '1px 6px', borderRadius: '4px', fontSize: '11px',
                                                        background: 'var(--bg-tertiary, #e9ecef)', color: 'var(--text-secondary)',
                                                    }}>
                                                        {expert.member_role}
                                                    </span>
                                                )}
                                                {!expert.done && (
                                                    <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>...</span>
                                                )}
                                            </div>
                                            <div style={{ fontSize: '13px', lineHeight: 1.6, color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>
                                                {expert.content || '...'}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Coordinator summary */}
                        {(rd.coordinatorContent || rd.coordinatorDone) && (
                            <div style={{
                                padding: '14px', borderRadius: '10px', marginTop: '8px',
                                background: 'var(--accent-bg, rgba(79, 70, 229, 0.05))',
                                border: '1px solid var(--accent-border, rgba(79, 70, 229, 0.2))',
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                                    <span style={{ fontSize: '14px' }}>🎯</span>
                                    <span style={{ fontSize: '14px', fontWeight: 600 }}>
                                        {team.members.find(m => m.agent_id === team.coordinator_agent_id)?.agent_name || '协调者'} · 综合总结
                                    </span>
                                </div>
                                <div style={{ fontSize: '13px', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                                    {rd.coordinatorContent || '...'}
                                </div>
                            </div>
                        )}
                    </div>
                ))}
            </div>

            {/* Input */}
            <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border-light, #e5e7eb)' }}>
                <div style={{ display: 'flex', gap: '8px' }}>
                    <input
                        value={input}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), sendMessage())}
                        placeholder={isStreaming ? '专家团正在回答中...' : '输入问题，专家团将协作回答...'}
                        disabled={isStreaming}
                        style={{
                            flex: 1, padding: '10px 14px', borderRadius: '8px',
                            border: '1px solid var(--border-light, #e5e7eb)',
                            fontSize: '14px', background: 'var(--bg-primary, #fff)',
                            color: 'var(--text-primary)',
                        }}
                    />
                    <button
                        onClick={sendMessage}
                        disabled={!input.trim() || isStreaming}
                        style={{
                            padding: '10px 20px', borderRadius: '8px', border: 'none',
                            background: 'var(--accent-primary, #4f46e5)', color: '#fff',
                            fontSize: '14px', fontWeight: 500, cursor: 'pointer',
                            opacity: (!input.trim() || isStreaming) ? 0.5 : 1,
                        }}
                    >
                        发送
                    </button>
                </div>
            </div>
        </div>
    );
}
