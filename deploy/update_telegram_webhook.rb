Channel::Telegram.all.each do |channel|
  puts "Updating Telegram webhook for bot: #{channel.bot_name}"
  if channel.save
    puts "Webhook updated successfully!"
  else
    puts "Failed to update webhook: #{channel.errors.full_messages.join(', ')}"
  end
end
