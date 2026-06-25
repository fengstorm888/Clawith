import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { agentTeamApi, agentApi } from '../services/api';
import type { AgentTeam, Agent } from '../types';

export default function AgentTeams() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const [showCreate, setShowCreate] = useState(false);
    const [createForm, setCreateForm] = useState({
        name: '',
        description: '',
        collaboration_mode: 'parallel',
        access_mode: 'company',
        coordinator_agent_id: '',
        selectedMembers: [] as { agent_id: string; member_role: string }[],
    });

    const { data: teams = [] } = useQuery({
        queryKey: ['agent-teams'],
        queryFn: agentTeamApi.list,
    });

    const { data: agents = [] } = useQuery<Agent[]>({
        queryKey: ['agents'],
        queryFn: () => agentApi.list(),
    });

    const createMutation = useMutation({
        mutationFn: (data: any) => agentTeamApi.create(data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['agent-teams'] });
            setShowCreate(false);
            setCreateForm({
                name: '', description: '', collaboration_mode: 'parallel',
                access_mode: 'company', coordinator_agent_id: '', selectedMembers: [],
            });
        },
    });

    const handleCreate = () => {
        if (!createForm.name.trim()) return;
        createMutation.mutate({
            name: createForm.name,
            description: createForm.description,
            collaboration_mode: createForm.collaboration_mode,
            access_mode: createForm.access_mode,
            coordinator_agent_id: createForm.coordinator_agent_id || null,
            members: createForm.selectedMembers,
        });
    };

    const toggleMember = (agentId: string) => {
        const existing = createForm.selectedMembers.find(m => m.agent_id === agentId);
        if (existing) {
            setCreateForm(f => ({ ...f, selectedMembers: f.selectedMembers.filter(m => m.agent_id !== agentId) }));
        } else {
            const agent = agents.find((a: Agent) => a.id === agentId);
            setCreateForm(f => ({
                ...f,
                selectedMembers: [...f.selectedMembers, { agent_id: agentId, member_role: agent?.role_description || '' }],
            }));
        }
    };

    return (
        <div style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
                <h1 style={{ margin: 0, fontSize: '24px', fontWeight: 600 }}>
                    {t('teams.title', '专家团')}
                </h1>
                <button
                    onClick={() => setShowCreate(true)}
                    style={{
                        padding: '8px 16px', borderRadius: '8px', border: 'none',
                        background: 'var(--accent-primary, #4f46e5)', color: '#fff',
                        cursor: 'pointer', fontSize: '14px', fontWeight: 500,
                    }}
                >
                    + {t('teams.create', '新建专家团')}
                </button>
            </div>

            {teams.length === 0 ? (
                <div style={{
                    textAlign: 'center', padding: '60px 20px', color: 'var(--text-tertiary)',
                }}>
                    <p style={{ fontSize: '16px', marginBottom: '8px' }}>{t('teams.empty', '还没有专家团')}</p>
                    <p style={{ fontSize: '14px' }}>{t('teams.emptyHint', '创建一个专家团，让多个 AI 专家协作回答问题')}</p>
                </div>
            ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '16px' }}>
                    {teams.map((team: AgentTeam) => (
                        <div
                            key={team.id}
                            onClick={() => navigate(`/teams/${team.id}/chat`)}
                            style={{
                                padding: '20px', borderRadius: '12px', cursor: 'pointer',
                                background: 'var(--bg-secondary, #f8f9fa)', border: '1px solid var(--border-light, #e5e7eb)',
                                transition: 'box-shadow 0.2s',
                            }}
                            onMouseEnter={e => (e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)')}
                            onMouseLeave={e => (e.currentTarget.style.boxShadow = 'none')}
                        >
                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                                <div style={{
                                    width: '40px', height: '40px', borderRadius: '10px',
                                    background: 'var(--accent-primary, #4f46e5)', color: '#fff',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    fontSize: '18px', fontWeight: 600, flexShrink: 0,
                                }}>
                                    {team.name.charAt(0).toUpperCase()}
                                </div>
                                <div>
                                    <div style={{ fontSize: '16px', fontWeight: 600 }}>{team.name}</div>
                                    <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                                        {team.members.length} {t('teams.members', '位专家')}
                                    </div>
                                </div>
                            </div>
                            {team.description && (
                                <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: '4px 0 8px', lineHeight: 1.5 }}>
                                    {team.description}
                                </p>
                            )}
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '8px' }}>
                                {team.members.slice(0, 5).map(m => (
                                    <span key={m.id} style={{
                                        padding: '2px 8px', borderRadius: '4px', fontSize: '11px',
                                        background: 'var(--bg-tertiary, #e9ecef)', color: 'var(--text-secondary)',
                                    }}>
                                        {m.agent_name || m.member_role}
                                    </span>
                                ))}
                                {team.members.length > 5 && (
                                    <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                                        +{team.members.length - 5}
                                    </span>
                                )}
                            </div>
                            <div style={{ marginTop: '8px', fontSize: '11px', color: 'var(--text-tertiary)' }}>
                                {team.collaboration_mode === 'parallel' && t('teams.parallel', '并行协作')}
                                {team.collaboration_mode === 'sequential' && t('teams.sequential', '顺序协作')}
                                {team.collaboration_mode === 'debate' && t('teams.debate', '辩论模式')}
                                {team.coordinator_agent_id && ` · ${t('teams.hasCoordinator', '有协调者')}`}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Create Modal */}
            {showCreate && (
                <div style={{
                    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 1000,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                }} onClick={e => e.target === e.currentTarget && setShowCreate(false)}>
                    <div style={{
                        background: 'var(--bg-primary, #fff)', borderRadius: '16px', padding: '24px',
                        width: '560px', maxHeight: '80vh', overflowY: 'auto',
                    }}>
                        <h2 style={{ margin: '0 0 16px', fontSize: '20px' }}>{t('teams.createTitle', '创建专家团')}</h2>

                        <div style={{ marginBottom: '12px' }}>
                            <label style={{ display: 'block', fontSize: '13px', marginBottom: '4px', fontWeight: 500 }}>
                                {t('teams.nameLabel', '团队名称')}
                            </label>
                            <input
                                value={createForm.name}
                                onChange={e => setCreateForm(f => ({ ...f, name: e.target.value }))}
                                placeholder={t('teams.namePlaceholder', '例如：技术评审专家组')}
                                style={inputStyle}
                            />
                        </div>

                        <div style={{ marginBottom: '12px' }}>
                            <label style={{ display: 'block', fontSize: '13px', marginBottom: '4px', fontWeight: 500 }}>
                                {t('teams.descLabel', '团队描述')}
                            </label>
                            <textarea
                                value={createForm.description}
                                onChange={e => setCreateForm(f => ({ ...f, description: e.target.value }))}
                                placeholder={t('teams.descPlaceholder', '这个专家组负责...')}
                                style={{ ...inputStyle, minHeight: '60px', resize: 'vertical' }}
                            />
                        </div>

                        <div style={{ display: 'flex', gap: '12px', marginBottom: '12px' }}>
                            <div style={{ flex: 1 }}>
                                <label style={{ display: 'block', fontSize: '13px', marginBottom: '4px', fontWeight: 500 }}>
                                    {t('teams.modeLabel', '协作模式')}
                                </label>
                                <select
                                    value={createForm.collaboration_mode}
                                    onChange={e => setCreateForm(f => ({ ...f, collaboration_mode: e.target.value }))}
                                    style={inputStyle}
                                >
                                    <option value="parallel">{t('teams.parallel', '并行协作')}</option>
                                    <option value="sequential">{t('teams.sequential', '顺序协作')}</option>
                                </select>
                            </div>
                            <div style={{ flex: 1 }}>
                                <label style={{ display: 'block', fontSize: '13px', marginBottom: '4px', fontWeight: 500 }}>
                                    {t('teams.coordinatorLabel', '协调者（可选）')}
                                </label>
                                <select
                                    value={createForm.coordinator_agent_id}
                                    onChange={e => setCreateForm(f => ({ ...f, coordinator_agent_id: e.target.value }))}
                                    style={inputStyle}
                                >
                                    <option value="">{t('teams.noCoordinator', '无协调者')}</option>
                                    {agents.map((a: Agent) => (
                                        <option key={a.id} value={a.id}>{a.name}</option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        <div style={{ marginBottom: '16px' }}>
                            <label style={{ display: 'block', fontSize: '13px', marginBottom: '4px', fontWeight: 500 }}>
                                {t('teams.selectMembers', '选择专家成员')}
                            </label>
                            <div style={{ maxHeight: '200px', overflowY: 'auto', border: '1px solid var(--border-light, #e5e7eb)', borderRadius: '8px', padding: '4px' }}>
                                {agents.length === 0 ? (
                                    <div style={{ padding: '12px', color: 'var(--text-tertiary)', fontSize: '13px' }}>
                                        {t('teams.noAgents', '暂无可选智能体，请先创建智能体')}
                                    </div>
                                ) : agents.map((a: Agent) => (
                                    <label key={a.id} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 8px', cursor: 'pointer', borderRadius: '4px' }}>
                                        <input
                                            type="checkbox"
                                            checked={createForm.selectedMembers.some(m => m.agent_id === a.id)}
                                            onChange={() => toggleMember(a.id)}
                                        />
                                        <span style={{ fontSize: '14px' }}>{a.name}</span>
                                        <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>{a.role_description}</span>
                                    </label>
                                ))}
                            </div>
                        </div>

                        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                            <button onClick={() => setShowCreate(false)} style={btnSecondary}>
                                {t('common.cancel', '取消')}
                            </button>
                            <button
                                onClick={handleCreate}
                                disabled={!createForm.name.trim() || createMutation.isPending}
                                style={{
                                    ...btnPrimary,
                                    opacity: (!createForm.name.trim() || createMutation.isPending) ? 0.5 : 1,
                                    cursor: (!createForm.name.trim() || createMutation.isPending) ? 'not-allowed' : 'pointer',
                                }}
                            >
                                {createMutation.isPending ? t('common.creating', '创建中...') : t('common.create', '创建')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

const inputStyle: React.CSSProperties = {
    width: '100%', padding: '8px 12px', borderRadius: '8px',
    border: '1px solid var(--border-light, #e5e7eb)', fontSize: '14px',
    background: 'var(--bg-primary, #fff)', color: 'var(--text-primary)',
    boxSizing: 'border-box',
};

const btnPrimary: React.CSSProperties = {
    padding: '8px 16px', borderRadius: '8px', border: 'none',
    background: 'var(--accent-primary, #4f46e5)', color: '#fff',
    fontSize: '14px', fontWeight: 500,
};

const btnSecondary: React.CSSProperties = {
    padding: '8px 16px', borderRadius: '8px', border: '1px solid var(--border-light, #e5e7eb)',
    background: 'transparent', color: 'var(--text-secondary)', fontSize: '14px', cursor: 'pointer',
};
