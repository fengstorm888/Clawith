import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { agentTeamApi, agentApi } from '../services/api';
import TeamChatPanel from '../components/TeamChatPanel';
import type { Agent } from '../types';

export default function AgentTeamDetail() {
    const { id: teamId } = useParams<{ id: string }>();
    const navigate = useNavigate();
    const { t } = useTranslation();
    const queryClient = useQueryClient();
    const [activeTab, setActiveTab] = useState<'chat' | 'members' | 'settings'>('chat');
    const [sessionId, setSessionId] = useState<string | null>(null);

    const { data: team, isLoading } = useQuery({
        queryKey: ['agent-team', teamId],
        queryFn: () => agentTeamApi.get(teamId!),
        enabled: !!teamId,
    });

    const { data: agents = [] } = useQuery<Agent[]>({
        queryKey: ['agents'],
        queryFn: () => agentApi.list(),
    });

    const { data: sessions = [] } = useQuery({
        queryKey: ['team-sessions', teamId],
        queryFn: () => agentTeamApi.sessions(teamId!),
        enabled: !!teamId && activeTab === 'chat',
    });

    // Auto-select latest session
    if (sessions.length > 0 && !sessionId && activeTab === 'chat') {
        setSessionId(sessions[0].id);
    }

    const addMemberMutation = useMutation({
        mutationFn: (data: { agent_id: string; member_role?: string }) => agentTeamApi.addMember(teamId!, data),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-team', teamId] }),
    });

    const removeMemberMutation = useMutation({
        mutationFn: (memberId: string) => agentTeamApi.removeMember(teamId!, memberId),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-team', teamId] }),
    });

    const deleteTeamMutation = useMutation({
        mutationFn: () => agentTeamApi.delete(teamId!),
        onSuccess: () => navigate('/teams'),
    });

    if (isLoading || !team) {
        return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-tertiary)' }}>加载中...</div>;
    }

    const availableAgents = agents.filter((a: Agent) => !team.members.some(m => m.agent_id === a.id));

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* Header */}
            <div style={{
                padding: '12px 20px', borderBottom: '1px solid var(--border-light, #e5e7eb)',
                display: 'flex', alignItems: 'center', gap: '12px',
            }}>
                <button onClick={() => navigate('/teams')} style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: 'var(--text-secondary)', fontSize: '14px',
                }}>
                    ← {t('teams.back', '返回')}
                </button>
                <div style={{
                    width: '36px', height: '36px', borderRadius: '8px',
                    background: 'var(--accent-primary, #4f46e5)', color: '#fff',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '16px', fontWeight: 600,
                }}>
                    {team.name.charAt(0).toUpperCase()}
                </div>
                <div>
                    <div style={{ fontSize: '16px', fontWeight: 600 }}>{team.name}</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                        {team.members.length} {t('teams.members', '位专家')} · {team.collaboration_mode === 'parallel' ? '并行协作' : '顺序协作'}
                    </div>
                </div>
            </div>

            {/* Tabs */}
            <div style={{ display: 'flex', gap: '0', borderBottom: '1px solid var(--border-light, #e5e7eb)' }}>
                {(['chat', 'members', 'settings'] as const).map(tab => (
                    <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        style={{
                            padding: '10px 20px', border: 'none', cursor: 'pointer',
                            background: 'transparent', fontSize: '14px', fontWeight: 500,
                            color: activeTab === tab ? 'var(--accent-primary, #4f46e5)' : 'var(--text-secondary)',
                            borderBottom: activeTab === tab ? '2px solid var(--accent-primary, #4f46e5)' : '2px solid transparent',
                        }}
                    >
                        {tab === 'chat' && t('teams.tabChat', '对话')}
                        {tab === 'members' && t('teams.tabMembers', '成员')}
                        {tab === 'settings' && t('teams.tabSettings', '设置')}
                    </button>
                ))}
            </div>

            {/* Tab content */}
            <div style={{ flex: 1, overflow: activeTab === 'chat' ? 'hidden' : 'auto' }}>
                {activeTab === 'chat' && (
                    <TeamChatPanel team={team} sessionId={sessionId} onSessionCreated={setSessionId} />
                )}

                {activeTab === 'members' && (
                    <div style={{ padding: '20px', maxWidth: '800px', margin: '0 auto' }}>
                        {/* Current members */}
                        <div style={{ marginBottom: '24px' }}>
                            <h3 style={{ fontSize: '14px', marginBottom: '12px', color: 'var(--text-secondary)' }}>
                                {t('teams.currentMembers', '当前成员')}
                            </h3>
                            {team.members.map(m => (
                                <div key={m.id} style={{
                                    display: 'flex', alignItems: 'center', gap: '12px',
                                    padding: '10px 12px', marginBottom: '8px', borderRadius: '8px',
                                    background: 'var(--bg-secondary, #f8f9fa)',
                                }}>
                                    <div style={{
                                        width: '32px', height: '32px', borderRadius: '8px',
                                        background: 'var(--accent-secondary, #6366f1)', color: '#fff',
                                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                                        fontSize: '14px', fontWeight: 600,
                                    }}>
                                        {(m.agent_name || '?').charAt(0)}
                                    </div>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ fontSize: '14px', fontWeight: 500 }}>{m.agent_name || 'Unknown'}</div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                                            {m.member_role || m.agent_role_description || '-'}
                                        </div>
                                    </div>
                                    {team.coordinator_agent_id === m.agent_id && (
                                        <span style={{
                                            padding: '2px 8px', borderRadius: '4px', fontSize: '11px',
                                            background: 'var(--accent-bg, rgba(79,70,229,0.1))',
                                            color: 'var(--accent-primary, #4f46e5)',
                                        }}>
                                            协调者
                                        </span>
                                    )}
                                    <button
                                        onClick={() => removeMemberMutation.mutate(m.id)}
                                        style={{
                                            background: 'none', border: 'none', cursor: 'pointer',
                                            color: 'var(--text-tertiary)', fontSize: '18px',
                                        }}
                                        title={t('teams.removeMember', '移除')}
                                    >
                                        ×
                                    </button>
                                </div>
                            ))}
                            {team.members.length === 0 && (
                                <div style={{ padding: '20px', color: 'var(--text-tertiary)', textAlign: 'center' }}>
                                    {t('teams.noMembers', '暂无成员')}
                                </div>
                            )}
                        </div>

                        {/* Add member */}
                        {availableAgents.length > 0 && (
                            <div>
                                <h3 style={{ fontSize: '14px', marginBottom: '12px', color: 'var(--text-secondary)' }}>
                                    {t('teams.addMember', '添加成员')}
                                </h3>
                                <div style={{ display: 'grid', gap: '8px' }}>
                                    {availableAgents.map((a: Agent) => (
                                        <div key={a.id} style={{
                                            display: 'flex', alignItems: 'center', gap: '12px',
                                            padding: '10px 12px', borderRadius: '8px',
                                            background: 'var(--bg-secondary, #f8f9fa)',
                                        }}>
                                            <div style={{
                                                width: '32px', height: '32px', borderRadius: '8px',
                                                background: 'var(--bg-tertiary, #e9ecef)',
                                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                fontSize: '14px', fontWeight: 600,
                                            }}>
                                                {a.name.charAt(0)}
                                            </div>
                                            <div style={{ flex: 1 }}>
                                                <div style={{ fontSize: '14px', fontWeight: 500 }}>{a.name}</div>
                                                <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>{a.role_description}</div>
                                            </div>
                                            <button
                                                onClick={() => addMemberMutation.mutate({ agent_id: a.id, member_role: (a.role_description || '').slice(0, 100) })}
                                                style={{
                                                    padding: '4px 12px', borderRadius: '6px', border: 'none',
                                                    background: 'var(--accent-primary, #4f46e5)', color: '#fff',
                                                    fontSize: '12px', cursor: 'pointer',
                                                }}
                                            >
                                                + {t('teams.add', '添加')}
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {activeTab === 'settings' && (
                    <div style={{ padding: '20px', maxWidth: '600px', margin: '0 auto' }}>
                        <div style={{ marginBottom: '16px' }}>
                            <label style={{ display: 'block', fontSize: '13px', marginBottom: '4px', fontWeight: 500 }}>团队名称</label>
                            <div style={{ padding: '8px 12px', borderRadius: '8px', background: 'var(--bg-secondary, #f8f9fa)', fontSize: '14px' }}>
                                {team.name}
                            </div>
                        </div>
                        <div style={{ marginBottom: '16px' }}>
                            <label style={{ display: 'block', fontSize: '13px', marginBottom: '4px', fontWeight: 500 }}>团队描述</label>
                            <div style={{ padding: '8px 12px', borderRadius: '8px', background: 'var(--bg-secondary, #f8f9fa)', fontSize: '14px', minHeight: '40px' }}>
                                {team.description || '-'}
                            </div>
                        </div>
                        <div style={{ marginBottom: '16px' }}>
                            <label style={{ display: 'block', fontSize: '13px', marginBottom: '4px', fontWeight: 500 }}>协作模式</label>
                            <div style={{ padding: '8px 12px', borderRadius: '8px', background: 'var(--bg-secondary, #f8f9fa)', fontSize: '14px' }}>
                                {team.collaboration_mode === 'parallel' ? '并行协作' : team.collaboration_mode === 'sequential' ? '顺序协作' : '辩论模式'}
                            </div>
                        </div>
                        <div style={{ marginBottom: '24px' }}>
                            <label style={{ display: 'block', fontSize: '13px', marginBottom: '4px', fontWeight: 500 }}>创建者</label>
                            <div style={{ padding: '8px 12px', borderRadius: '8px', background: 'var(--bg-secondary, #f8f9fa)', fontSize: '14px' }}>
                                {team.creator_username || '-'}
                            </div>
                        </div>

                        <div style={{ paddingTop: '16px', borderTop: '1px solid var(--border-light, #e5e7eb)' }}>
                            <button
                                onClick={() => {
                                    if (confirm(t('teams.confirmDelete', '确定删除这个专家团吗？所有对话记录将丢失。'))) {
                                        deleteTeamMutation.mutate();
                                    }
                                }}
                                style={{
                                    padding: '8px 16px', borderRadius: '8px',
                                    border: '1px solid #ef4444', background: 'transparent',
                                    color: '#ef4444', fontSize: '14px', cursor: 'pointer',
                                }}
                            >
                                {t('teams.delete', '删除专家团')}
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
