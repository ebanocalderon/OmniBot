bot = AgentBot.find_by(name: "Qwen Assistant")
if bot.nil?
  bot = AgentBot.create!(name: "Qwen Assistant", description: "Helpful AI Bot", outgoing_url: "http://10.0.0.42:8000/chatwoot/webhook")
end
puts "TOKEN:" + bot.access_token.token

# Attach to all existing inboxes
Inbox.all.each do |inbox|
  unless AgentBotInbox.exists?(inbox_id: inbox.id, agent_bot_id: bot.id)
    AgentBotInbox.create!(inbox_id: inbox.id, agent_bot_id: bot.id)
    puts "Attached to inbox: #{inbox.name} (id: #{inbox.id})"
  end
end
